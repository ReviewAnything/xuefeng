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
PROVINCE_ADAPTERS = {
    "广东": {"notices": GD_NOTICES, "parse": "_parse_guangdong"},
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
        r'<a[^>]*href="((?:https?://[^"]*?)?/?attachment/[^"]+?\.(?:zip|pdf))"[^>]*>(.*?)</a>',
        html, re.S,
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


def _rows_from_lines(lines: list[tuple[float, float, str]]) -> list[list[str]]:
    """从 (x0, y0, text) 行集合重建数据行（纯函数，可独立测试）。"""
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
        if len(cells) != N_COLS:
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


def _page_rows(page) -> list[list[str]]:
    """按 y 聚类成行；每行按 x 排序后应恰为 5 个单元格（序位定列，
    不做 x 聚类——数字位数变化会让相邻列的 x 范围交叠，聚类不稳）。"""
    lines = []
    for el in page:
        if isinstance(el, LTTextContainer):
            for ln in el:
                if isinstance(ln, LTTextLineHorizontal):
                    t = ln.get_text().strip()
                    if t:
                        lines.append((ln.x0, ln.y0, t))
    return _rows_from_lines(lines)


def parse_gd_pdf(pdf_bytes: bytes) -> tuple[list[list[int]], str]:
    """返回 rows=[[score, seg_ben, cum_ben, seg_zhuan, cum_zhuan], ...]（score 降序）与顶部分数备注。"""
    rows: list[list] = []
    top_note = ""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        path = f.name
    try:
        for page in extract_pages(path):
            rows.extend(_page_rows(page))
    finally:
        Path(path).unlink(missing_ok=True)
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


def validate_rows(rows: list[list[int]]) -> None:
    """强校验：score 降序唯一；本科/专科各自 累计=前项+本段 且累计单调不减。"""
    prev_b = prev_z = None
    prev_score = None
    for score, sb, cb, sz, cz in rows:
        if prev_score is not None and score >= prev_score:
            raise ValueError(f"分数非严格降序: {prev_score} -> {score}")
        if sb < 0 or sz < 0 or cb < 0 or cz < 0:
            raise ValueError(f"负数: score={score}")
        if prev_b is not None:
            if cb != prev_b + sb:
                raise ValueError(f"本科累计断裂 score={score}: {prev_b}+{sb}!={cb}")
            if cz != prev_z + sz:
                raise ValueError(f"专科累计断裂 score={score}: {prev_z}+{sz}!={cz}")
        else:
            if cb != sb or cz != sz:
                raise ValueError(f"首行累计应等于本段: score={score}")
        prev_b, prev_z, prev_score = cb, cz, score


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
