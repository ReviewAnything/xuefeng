#!/usr/bin/env python3
"""省考试院一分一段表抓取管线（年度罗盘数据第二梯队）。

当前覆盖：
- 广东（eea.gd.gov.cn）：2022–2026 普通类（物理/历史）分数段统计表。
  通知页 → ZIP 附件 → PDF（pdfminer 按坐标重建行）→ 强校验 → 落盘
  ``backend/data/rank_tables/{year}/广东.json``。

落盘格式（rows 为紧凑数组 [score, seg_ben, cum_ben, seg_zhuan, cum_zhuan]，score 降序）：
    {
      "meta": {
        "year": 2025, "province": "广东", "data_source": "official",
        "source_url": "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4734449.html",
        "attachment_url": ".../4734449.zip",
        "attachment_sha256": "...", "fetched_at": "...",
        "subjects": {"物理类": {"rows": 692, "top_note": "697（含以上）"}, ...}
      },
      "subjects": {"物理类": {"rows": [[697, 19, 19, 19, 19], ...]}, ...}
    }

硬规矩：
- 每份数据必须带可点开的 source_url 与附件 sha256，否则整份拒收；
- 校验不过（累计≠前项+本段 / 单调性破坏 / 列错位）整份拒收，绝不部分落盘；
- 本脚本只做「采集+落盘」，不自动把任何行升格进 school_lines。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

BACKEND = Path(__file__).resolve().parents[1]
OUT_DIR = BACKEND / "data" / "rank_tables"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# 省份适配器注册表：每个省一个 dict(year -> 通知页 URL)
# ---------------------------------------------------------------------------
GD_NOTICES = {
    2026: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4916195.html",
    2025: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4734449.html",
    2024: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4445715.html",
    2023: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4207233.html",
    2022: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_3986282.html",
}
# 山东（sdzk.cn）：栏目「夏季高考 > 分段表」，附件为 .xls（每档 2 列：本段/累计）
SD_NOTICES = {
    2026: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=7258",
    2025: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=6943",
    2024: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=6577",
    2023: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=6212",
    2022: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=5794",
}
PROVINCE_ADAPTERS = {
    "广东": {"notices": GD_NOTICES, "parse": "_parse_guangdong"},
    "山东": {"notices": SD_NOTICES, "parse": "_parse_shandong"},
}

FOOTER_PAT = re.compile(r"^第\s*\d+\s*页|^广东省教育考试院$|^附件\d*$")


# ---------------------------------------------------------------------------
# 通用抓取
# ---------------------------------------------------------------------------
def http_get(url: str, timeout: int = 60) -> bytes:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.content


def find_attachments(notice_url: str) -> list[dict]:
    """通知页附件清单：[{url, label}]。兼容三种形态——
    ZIP 打包（2024/2025）、逐类 PDF 锚文本带类名（2022/2026）、单个合并 PDF（2023「下载附件」）。
    """
    html = http_get(notice_url).decode("utf-8", "ignore")
    out: list[dict] = []
    seen = set()
    for m in re.finditer(
        r'<a[^>]*href="([^"]+?\.(?:zip|pdf|xls|xlsx))"[^>]*>(.*?)</a>',
        html, re.S | re.I,
    ):
        url, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if url.startswith("/"):
            url = "https://" + notice_url.split("/")[2] + url
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "label": label, "kind": url.rsplit(".", 1)[-1]})
    if not out:
        raise ValueError(f"通知页无附件: {notice_url}")
    return out


def subject_of(label: str) -> str | None:
    """附件标签 -> 科类。只收普通类物理/历史（体育艺术类不要）。"""
    if ("普通类" in label or "普通" in label) and "分数段" in label:
        if "物理" in label:
            return "物理类"
        if "历史" in label:
            return "历史类"
    return None


def sniff_subject(pdf_bytes: bytes) -> str | None:
    """无名合并 PDF：从首页文本嗅探含哪些科类标题（2023 形态）。"""
    from pdfminer.high_level import extract_text
    import tempfile, pathlib
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        p = f.name
    try:
        head = extract_text(p, page_numbers=[0, 1]) or extract_text(p, maxpages=2)
    finally:
        pathlib.Path(p).unlink(missing_ok=True)
    found = []
    if "物理" in head and "分数段" in head:
        found.append("物理类")
    if "历史" in head and "分数段" in head:
        found.append("历史类")
    return "合并" if len(found) > 1 else (found[0] if found else None)


# ---------------------------------------------------------------------------
# PDF 解析（广东：文化总分 | 本科段/本科累计 | 专科段/专科累计 五列）
# ---------------------------------------------------------------------------
NUM_PAT = re.compile(r"^\d+$")
SCORE_PAT = re.compile(r"^(\d{3})(（含以上）|\+)?$")

# 行容差（pt）：同一行 5 个单元格 y0 基本一致；行距 ~13pt 远大于此
ROW_TOL = 3.0
N_COLS = 5  # 分数 | 本科段 | 本科累计 | 专科段 | 专科累计
N_COLS_SINGLE = 3  # 分数 | 本段 | 累计（单档位省份）


def _rows_from_lines(
    lines: list[tuple[float, float, str]], n_cols: int = N_COLS
) -> list[list[str]]:
    """从 (x0, y0, text) 行集合重建数据行（纯函数，可独立测试）。

    ``n_cols`` 为每行单元格数：5=广东双档位（分数|本科段|本科累计|专科段|专科累计），
    3=单档位（分数|本段|累计）。行内按 x 排序后「序位定列」——不做 x 聚类。
    """
    drop_keys = ("文化总分", "分数段人数", "累计人数", "本科加分", "专科加分", "含本、专科")
    lines = [
        (x, y, t) for x, y, t in lines
        if not any(k in t for k in drop_keys) and not FOOTER_PAT.match(t)
    ]
    if not lines:
        return []
    lines.sort(key=lambda r: -r[1])
    rows, cur, cur_y = [], [], None
    for x, y, t in lines:
        if cur_y is None or abs(y - cur_y) <= ROW_TOL:
            cur.append((x, t))
            cur_y = y if cur_y is None else cur_y
        else:
            rows.append(cur)
            cur, cur_y = [(x, t)], y
    if cur:
        rows.append(cur)
    out = []
    for cells in rows:
        if len(cells) != n_cols:
            continue  # 标题/表头/孤立行——非数据行
        cells.sort(key=lambda c: c[0])
        score_t = cells[0][1]
        if not SCORE_PAT.match(score_t):
            continue
        try:
            nums = [int(t) for _, t in cells[1:]]
        except ValueError:
            continue
        out.append([score_t] + nums)
    return out


def _page_rows(page, n_cols: int = N_COLS) -> list[list[str]]:
    """按 y 聚类成行；每行按 x 排序后应恰为 n_cols 个单元格（序位定列，
    不做 x 聚类——数字位数变化会让相邻列的 x 范围交叠，聚类不稳）。"""
    lines = []
    for el in page:
        if isinstance(el, LTTextContainer):
            for ln in el:
                if isinstance(ln, LTTextLineHorizontal):
                    t = ln.get_text().strip()
                    if t:
                        lines.append((ln.x0, ln.y0, t))
    return _rows_from_lines(lines, n_cols)


def _pdf_rows(pdf_bytes: bytes, n_cols: int = N_COLS) -> list[list[str]]:
    rows: list[list] = []
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        path = f.name
    try:
        for page in extract_pages(path):
            rows.extend(_page_rows(page, n_cols))
    finally:
        Path(path).unlink(missing_ok=True)
    return rows


def _finalize(rows: list[list[str]]) -> tuple[list[list[int]], str]:
    """原始单元格行 -> 整型行 + 顶部分数备注（如「697（含以上）」）。"""
    if not rows:
        raise ValueError("PDF 未解析出任何数据行")
    parsed, top_note = [], ""
    for i, r in enumerate(rows):
        m = SCORE_PAT.match(r[0])
        score = int(m.group(1))
        if i == 0 and m.group(2):
            top_note = r[0]
        parsed.append([score] + r[1:])
    return parsed, top_note


def parse_gd_pdf(pdf_bytes: bytes) -> tuple[list[list[int]], str]:
    """返回 rows=[[score, seg_ben, cum_ben, seg_zhuan, cum_zhuan], ...]（score 降序）与顶部分数备注。"""
    return _finalize(_pdf_rows(pdf_bytes, N_COLS))


def parse_single_pdf(pdf_bytes: bytes) -> tuple[list[list[int]], str]:
    """单档位省份（分数|本段|累计 三列）PDF。返回 [[score, seg, cum], ...]。"""
    return _finalize(_pdf_rows(pdf_bytes, N_COLS_SINGLE))



def validate_rows(rows: list[list[int]]) -> None:
    """强校验：score 降序唯一；各档位 累计=前项+本段 且累计单调不减。

    支持两种行宽：3=（score|本段|累计）、5=（score|本科段|本科累计|专科段|专科累计）。
    """
    width = len(rows[0]) if rows else 0
    if width not in (3, 5):
        raise ValueError(f"不支持的列宽: {width}")
    # 档位对：[(本段下标, 累计下标), ...]
    pairs = [(1, 2)] if width == 3 else [(1, 2), (3, 4)]
    prev = [None] * len(pairs)
    prev_score = None
    for r in rows:
        if len(r) != width:
            raise ValueError(f"行宽不一致: {len(r)} != {width}")
        score = r[0]
        if prev_score is not None and score >= prev_score:
            raise ValueError(f"分数非严格降序: {prev_score} -> {score}")
        for i, (si, ci) in enumerate(pairs):
            seg, cum = r[si], r[ci]
            if seg < 0 or cum < 0:
                raise ValueError(f"负数: score={score}")
            if prev[i] is None:
                # 顶部分数桶常被截断（如「692 分及以上共 54 人」而 692 只有 7 人），
                # 故首行只要求 累计 >= 本段，不强求相等；截断量由调用方记入 top_note。
                if cum < seg:
                    raise ValueError(f"首行累计小于本段: score={score} {seg}>{cum}")
            elif cum != prev[i] + seg:
                raise ValueError(f"累计断裂 score={score}: {prev[i]}+{seg}!={cum}")
            prev[i] = cum
        prev_score = score



# ---------------------------------------------------------------------------
# 广东适配
# ---------------------------------------------------------------------------
def _parse_guangdong(year: int) -> dict:
    notice_url = GD_NOTICES[year]
    atts = find_attachments(notice_url)
    subjects: dict = {}
    sha_all: dict[str, str] = {}

    def consume_pdf(blob: bytes, att_url: str, subj: str):
        rows, top_note = parse_gd_pdf(blob)
        validate_rows(rows)
        subjects[subj] = {"rows": rows, "top_note": top_note}
        sha_all[subj] = hashlib.sha256(blob).hexdigest()
        sha_all[subj + "_url"] = att_url

    zips = [a for a in atts if a["kind"] == "zip"]
    if zips:
        blob = http_get(zips[0]["url"], timeout=120)
        sha_all["zip"] = hashlib.sha256(blob).hexdigest()
        sha_all["zip_url"] = zips[0]["url"]
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            zf = zipfile.ZipFile(io.BytesIO(blob))
            for info in zf.infolist():
                if info.is_dir():
                    continue
                subj = subject_of(info.filename)
                if subj:
                    consume_pdf(zf.read(info), zips[0]["url"], subj)
    pdfs = [a for a in atts if a["kind"] == "pdf"]
    for a in pdfs:
        subj = subject_of(a["label"])
        if not subj:
            continue
        blob = http_get(a["url"], timeout=120)
        consume_pdf(blob, a["url"], subj)
    # 无锚文本类名（如单个「下载附件」PDF）：下载嗅探
    if not subjects:
        for a in pdfs:
            blob = http_get(a["url"], timeout=180)
            kind = sniff_subject(blob)
            if kind in ("物理类", "历史类"):
                consume_pdf(blob, a["url"], kind)
    if not subjects:
        raise ValueError(f"未能取到普通类 物理/历史 数据: {[a['label'] for a in atts]}")
    return {
        "meta": {
            "year": year,
            "province": "广东",
            "data_source": "official",
            "source_url": notice_url,
            "attachment_url": sha_all.get("zip_url") or sha_all.get("物理类_url", ""),
            "attachment_sha256": sha_all.get("zip") or sha_all.get("物理类", ""),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "subjects": subjects,
    }


# ---------------------------------------------------------------------------
# Excel 解析（山东式：分数段 + 多档位 × [本段人数, 累计人数]）
# ---------------------------------------------------------------------------
def _int_of(v) -> int | None:
    """单元格 -> 整数。兼容 float、'692'、'692分'、'692（含以上）'；空/不可解析返回 None。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if v == v and v >= 0 else None
    s = str(v).strip().replace(",", "")
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else None


def parse_xls_tracks(blob: bytes) -> dict[str, dict]:
    """解析「每档 2 列（本段/累计）」的宽表，返回 {档名: {rows: [[score, seg, cum]], top_note}}。

    表头两级：第一级为档位名（合并单元格，向左填充），第二级为「本段人数/累计人数」。
    只保留能通过逐行「累计=前项+本段」校验的档位——校验不过的档位整档丢弃并记入
    ``_rejected``（不静默半截落盘）。
    """
    import xlrd

    wb = xlrd.open_workbook(file_contents=blob)
    for sh in wb.sheets():
        hdr = None
        for r in range(min(10, sh.nrows)):
            vals = [str(sh.cell_value(r, c)).strip() for c in range(sh.ncols)]
            if not (vals and "分数" in vals[0]):
                continue
            nxt = [str(sh.cell_value(r + 1, c)).strip() for c in range(sh.ncols)] \
                if r + 1 < sh.nrows else []
            # 两级表头：本级为档位名，下一级为「本段人数/累计人数」
            if any("本段" in v for v in nxt) or any("本段" in v for v in vals):
                hdr = r
                break
        if hdr is None:
            continue
        # 档位名：第一级表头向左填充（合并单元格在 xls 里只有首格有值）
        groups: list[str] = []
        cur = ""
        for c in range(1, sh.ncols):
            v = str(sh.cell_value(hdr, c)).strip()
            if v:
                cur = v
            groups.append(cur)
        # 子表头：本段列与其右侧的累计列配对
        sub_row = hdr + 1 if any(
            "本段" in str(sh.cell_value(hdr + 1, c)) for c in range(sh.ncols)
        ) else hdr
        pairs = []  # [(档名, seg_idx, cum_idx)]
        for c in range(1, sh.ncols):
            sub = str(sh.cell_value(sub_row, c)).strip()
            if "本段" in sub and c + 1 < sh.ncols:
                pairs.append((groups[c - 1], c, c + 1))
        if not pairs:
            continue
        data: dict[str, dict] = {name: {"rows": [], "top_note": ""} for name, _, _ in pairs}
        for r in range(sub_row + 1, sh.nrows):
            score = _int_of(sh.cell_value(r, 0))
            if score is None or not (0 <= score <= 750):
                continue
            for name, si, ci in pairs:
                seg, cum = _int_of(sh.cell_value(r, si)), _int_of(sh.cell_value(r, ci))
                if seg is None or cum is None:
                    continue
                data[name]["rows"].append([score, seg, cum])
        out, rejected = {}, []
        for name, blk in data.items():
            if not blk["rows"]:
                continue
            try:
                validate_rows(blk["rows"])
            except ValueError as e:
                rejected.append(f"{name}: {e}")
                continue
            # 顶部截断桶：最高分只统计「X 分及以上」合计人数
            r0 = blk["rows"][0]
            if r0[2] > r0[1]:
                blk["top_note"] = f"{r0[0]}分及以上共{r0[2]}人"
            out[name] = blk
        if rejected:
            out["_rejected"] = rejected
        if out:
            return out
    raise ValueError("Excel 未找到「分数段 + 本段人数/累计人数」表头")


# ---------------------------------------------------------------------------
# 山东适配（3+3 综合改革：全体 + 6 个选考科目各一套位次）
# ---------------------------------------------------------------------------
def _parse_shandong(year: int) -> dict:
    notice_url = SD_NOTICES[year]
    atts = find_attachments(notice_url)
    picked = [a for a in atts if "夏季高考" in a["label"] and "一分一段" in a["label"]]
    if not picked:
        raise ValueError(f"未找到夏季高考一分一段附件: {[a['label'] for a in atts]}")
    att = picked[0]
    blob = http_get(att["url"], timeout=180)
    tracks = parse_xls_tracks(blob)
    rejected = tracks.pop("_rejected", [])
    if "全体" not in tracks:
        raise ValueError(f"缺「全体」档位: {sorted(tracks)}")
    subjects: dict = {}
    # 全体 -> 综合（3+3 省不区分物理/历史类）；选考X 单独存档
    subjects["综合"] = tracks.pop("全体")
    for name, blk in tracks.items():
        subjects[name] = blk
    for name in subjects:
        subjects[name]["rows"].sort(key=lambda r: -r[0])
    return {
        "meta": {
            "year": year,
            "province": "山东",
            "data_source": "official",
            "source_url": notice_url,
            "attachment_url": att["url"],
            "attachment_sha256": hashlib.sha256(blob).hexdigest(),
            "subject_scheme": "3+3",
            "note": "综合=全体考生；选考X=该选考科目考生内部位次（非物理/历史类）",
            "rejected_tracks": rejected,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "subjects": subjects,
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def save(doc: dict) -> Path:
    year, prov = doc["meta"]["year"], doc["meta"]["province"]
    d = OUT_DIR / str(year)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{prov}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return p


def main() -> int:
    provinces = sys.argv[1:] or list(PROVINCE_ADAPTERS)
    ok = True
    for prov in provinces:
        adapter = PROVINCE_ADAPTERS[prov]
        for year in sorted(adapter["notices"], reverse=True):
            try:
                doc = getattr(sys.modules[__name__], adapter["parse"])(year)
                p = save(doc)
                summary = {
                    s: {"rows": len(v["rows"]), "top": v["rows"][0][0], "bottom": v["rows"][-1][0]}
                    for s, v in doc["subjects"].items()
                }
                print(f"OK  {prov} {year} -> {p.relative_to(BACKEND)}  {summary}")
            except Exception as e:  # noqa: BLE001 - 逐省逐年隔离失败
                ok = False
                print(f"FAIL {prov} {year}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
