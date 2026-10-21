"""一分一段采集的公共底座：抓取、版式解析、强校验、落盘。

设计要点（踩过的坑，改之前先看这里）：
- **列定位不用 x 聚类/固定分桶**：历史类 PDF 整体左移几十 pt、大数字变宽会让
  相邻列的 x 范围交叠。统一用「按 y 拼行 + 行内按 x 排序取第 N 个单元格」。
- **并排多组版式**（浙江/湖北每页横排 3 组）：同一个 y 上的三格属于三个不同
  分数段，必须先用表头 x 切组；组的归属规则是「归左侧最近的那个表头」，
  用中点会切错（组内累计列的 x 会越过两表头中点）。
- **首行允许截断桶**：官方表顶部常写「X 分及以上共 N 人」（N 远大于该分人数），
  首行只要求 累计 >= 本段，不要求相等。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
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

# 行容差（pt）：同一行各单元格 y0 基本一致；行距通常 ~13pt
ROW_TOL = 3.0
N_COLS = 5          # 分数 | 本科段 | 本科累计 | 专科段 | 专科累计（广东双档位）
N_COLS_SINGLE = 3   # 分数 | 本段 | 累计（单档位省）

NUM_PAT = re.compile(r"^\d+$")
SCORE_PAT = re.compile(r"^(\d{3})(（含以上）|\+|及以上)?$")
SCORE_UP_PAT = re.compile(r"^(\d{3})\s*(?:↑|（含以上）|\+|及以上)?$")
# 并排多组版的表头：浙江是「总分」，湖北是「分数 人数 累计人数」
BLOCK_HEADER_PAT = re.compile(r"^(?:总分|档分|分数)\s*(?:人数|本段人数|同分人数)?\s*(?:累计人数)?$")
FOOTER_PAT = re.compile(
    r"^第\s*\d+\s*页|^广东省教育考试院$|^附件\d*$|^湖南省教育考试院$|^湖北省教育考试院$"
)


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------
def _curl_get(url: str, timeout: int = 60) -> bytes:
    """requests 走不通时的兜底通道。

    少数省站（如 hneeb.cn）的证书链在 requests/OpenSSL 下握手失败，而系统 curl
    可以正常访问——不是反爬，是证书兼容问题，所以用 curl 取同一 URL，不做绕过。
    """
    out = subprocess.run(
        ["curl", "-sSL", "--max-time", str(timeout), "-A", UA, url],
        capture_output=True, check=False,
    )
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"抓取失败（curl {out.returncode}）: {url}")
    return out.stdout


def http_get(url: str, timeout: int = 60) -> bytes:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        return r.content
    except (requests.exceptions.SSLError,
            requests.exceptions.ConnectionError) as exc:
        # 证书链不兼容 / 连接被重置（TLS 指纹差异）都走 curl 兜底
        try:
            return _curl_get(url, timeout)
        except Exception:
            raise exc


def decode_html(blob: bytes) -> str:
    """省站编码混乱（UTF-8 / GBK 都有），按替换字符数量择优。"""
    best, best_bad = "", 10 ** 9
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            t = blob.decode(enc)
        except UnicodeDecodeError:
            t = blob.decode(enc, "ignore")
        bad = t.count("\ufffd")
        if bad < best_bad:
            best, best_bad = t, bad
        if bad == 0:
            break
    return best


def http_get_html(url: str, timeout: int = 60) -> str:
    return decode_html(http_get(url, timeout))


_decode_html = decode_html  # 旧名兼容


def find_attachments(notice_url: str, kinds: str = "zip|pdf|xls|xlsx") -> list[dict]:
    """通知页附件清单：[{url, label, kind}]（支持相对链接）。"""
    html = http_get_html(notice_url)
    out: list[dict] = []
    seen = set()
    for m in re.finditer(
        rf'<a[^>]*href="([^"]+?\.(?:{kinds}))"[^>]*>(.*?)</a>',
        html, re.S | re.I,
    ):
        url, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://" + notice_url.split("/")[2] + url
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "label": label, "kind": url.rsplit(".", 1)[-1].lower()})
    if not out:
        raise ValueError(f"通知页无附件: {notice_url}")
    return out


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 版式 A：按 y 拼行、行内序位定列（广东式，单组 N 列）
# ---------------------------------------------------------------------------
def _rows_from_lines(
    lines: list[tuple[float, float, str]], n_cols: int = N_COLS
) -> list[list[str]]:
    """从 (x0, y0, text) 行集合重建数据行（纯函数，可独立测试）。

    ``n_cols`` 为每行单元格数：5=双档位（分数|本科段|本科累计|专科段|专科累计），
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


def page_lines(page) -> list[tuple[float, float, str]]:
    lines = []
    for el in page:
        if isinstance(el, LTTextContainer):
            for ln in el:
                if isinstance(ln, LTTextLineHorizontal):
                    t = ln.get_text().strip()
                    if t:
                        lines.append((ln.x0, ln.y0, t))
    return lines


def _page_rows(page, n_cols: int = N_COLS) -> list[list[str]]:
    return _rows_from_lines(page_lines(page), n_cols)


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
        raise ValueError("未解析出任何数据行")
    parsed, top_note = [], ""
    for i, r in enumerate(rows):
        m = SCORE_PAT.match(r[0])
        score = int(m.group(1))
        if i == 0 and m.group(2):
            top_note = r[0]
        parsed.append([score] + r[1:])
    return parsed, top_note


def parse_gd_pdf(pdf_bytes: bytes) -> tuple[list[list[int]], str]:
    """双档位 PDF（5 列）。返回 rows 与顶部分数备注。"""
    return _finalize(_pdf_rows(pdf_bytes, N_COLS))


def parse_single_pdf(pdf_bytes: bytes) -> tuple[list[list[int]], str]:
    """单档位 PDF（分数|本段|累计 三列）。"""
    return _finalize(_pdf_rows(pdf_bytes, N_COLS_SINGLE))


# ---------------------------------------------------------------------------
# 版式 B：整页并排多组（浙江/湖北，每页 2–3 组）
# ---------------------------------------------------------------------------
def _page_block_rows(page) -> list[list[int]]:
    """把一页重建为 [[score, seg, cum], ...]。

    版式：整页横向并排 N 组三列，**同 y 的行分属不同分数段**（第 1 组跑完才轮到
    第 2 组），因此不能按 y 拼行；要先用表头 x 切出各组，再组内自上而下读、
    组间顺序即分数降序。列归属规则是「归左侧最近的那个表头」。
    """
    import collections

    lines = page_lines(page)
    byy: dict[float, list[float]] = collections.defaultdict(list)
    for x, y, t in lines:
        if BLOCK_HEADER_PAT.match(t):
            byy[round(y, 1)].append(x)
    if not byy:
        return []
    hy, hxs = max(byy.items(), key=lambda kv: len(kv[1]))
    if len(hxs) < 2:
        return []  # 单组版式交给 _rows_from_lines
    hxs = sorted(hxs)

    def block_of(x: float) -> int:
        return max(i for i, hx in enumerate(hxs) if x >= hx - 6)

    data = [
        (x, y, t) for x, y, t in lines
        if y < hy - 4 and not any(k in t for k in ("人数", "累计", "总分", "档分"))
        and not re.search(r"[省市]20\d\d\s*年", t)
    ]
    data.sort(key=lambda r: (-r[1], r[0]))
    rows, cur, cy = [], [], None
    for x, y, t in data:
        if cy is None or abs(y - cy) <= ROW_TOL:
            cur.append((x, t))
            cy = y if cy is None else cy
        else:
            rows.append(cur)
            cur, cy = [(x, t)], y
    if cur:
        rows.append(cur)

    out: list[list[int]] = []
    for bi in range(len(hxs)):
        for cells in rows:
            cbi = [(x, t) for x, t in sorted(cells) if block_of(x) == bi]
            if not cbi:
                continue
            m = SCORE_UP_PAT.match(cbi[0][1])
            if not m:
                continue
            nums = [int(t) for _, t in cbi[1:] if re.fullmatch(r"\d+", t)]
            if len(nums) == 2:
                out.append([int(m.group(1))] + nums)
            elif len(nums) == 1:
                # 顶部截断桶（如「693↑」）只印一个数：人数=累计
                out.append([int(m.group(1)), nums[0], nums[0]])
    return out


def parse_blocked_pdf(pdf_bytes: bytes) -> tuple[list[list[int]], str]:
    rows: list[list[int]] = []
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        path = f.name
    try:
        for page in extract_pages(path):
            rows.extend(_page_block_rows(page))
    finally:
        Path(path).unlink(missing_ok=True)
    if not rows:
        raise ValueError("PDF 未解析出任何数据行（分块版式）")
    return rows, (f"{rows[0][0]}↑" if rows[0][1] == rows[0][2] else "")


# ---------------------------------------------------------------------------
# 版式 C：HTML 表格（湖南式，服务端直出 <tr><td>）
# ---------------------------------------------------------------------------
def parse_html_table(html: str) -> tuple[list[list[int]], str, dict | None]:
    """从 HTML 表格取 [score, seg, cum]。表尾「N 分以下」桶不计入 rows，
    作为 below_bucket 返回（它不是某个具体分数，混进 rows 会让位次失真）。

    坑：湖南 2025 的源表把「100 以下」这一行的首格也印成 ``100``（与上一行同分），
    只靠文本分不出来。判据是结构性的——**末行与上一行同分，且 累计=前项+本段**，
    那它就是「N 分以下」合计桶（真实分数不会出现两行同分）。
    """
    rows: list[list[int]] = []
    below: dict | None = None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [
            re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c))
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        ]
        if len(cells) != 3:
            continue
        m = re.fullmatch(r"(\d{3})", cells[0])
        if m and cells[1].isdigit() and cells[2].isdigit():
            rows.append([int(m.group(1)), int(cells[1]), int(cells[2])])
            continue
        mb = re.fullmatch(r"(\d{3})分?以下", cells[0])
        if mb and cells[1].isdigit() and cells[2].isdigit():
            below = {"score_below": int(mb.group(1)),
                     "seg": int(cells[1]), "cum": int(cells[2])}
    if not rows:
        raise ValueError("HTML 表格未解析出任何数据行")
    # 末行与上一行同分且累计能接上 -> 「N 分以下」合计桶
    if (len(rows) >= 2 and rows[-1][0] == rows[-2][0]
            and rows[-1][2] == rows[-2][2] + rows[-1][1]):
        last = rows.pop()
        below = below or {"score_below": last[0], "seg": last[1], "cum": last[2]}
    top_note = f"{rows[0][0]}↑" if rows[0][1] == rows[0][2] else ""
    return rows, top_note, below


# ---------------------------------------------------------------------------
# Excel（山东式：分数段 + 多档位 × [本段人数, 累计人数]）
# ---------------------------------------------------------------------------
def _int_of(v) -> int | None:
    """单元格 -> 整数。兼容 float、'692'、'692分'、'692（含以上）'。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if v == v and v >= 0 else None
    s = str(v).strip().replace(",", "")
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else None


def parse_xls_tracks(blob: bytes) -> dict[str, dict]:
    """解析「每档 2 列（本段/累计）」的宽表，返回 {档名: {rows, top_note}}。

    表头两级：第一级为档位名（合并单元格向左填充），第二级为「本段人数/累计人数」。
    校验不过的档位整档丢弃并记入 ``_rejected``（不静默半截落盘）。
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
            if any("本段" in v for v in nxt) or any("本段" in v for v in vals):
                hdr = r
                break
        if hdr is None:
            continue
        groups: list[str] = []
        cur = ""
        for c in range(1, sh.ncols):
            v = str(sh.cell_value(hdr, c)).strip()
            if v:
                cur = v
            groups.append(cur)
        sub_row = hdr + 1 if any(
            "本段" in str(sh.cell_value(hdr + 1, c)) for c in range(sh.ncols)
        ) else hdr
        pairs = []
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
# 强校验
# ---------------------------------------------------------------------------
def validate_rows(rows: list[list[int]]) -> None:
    """强校验：score 严格降序；各档位 累计=前项+本段。

    支持行宽 3=（score|本段|累计）、5=（score|本科段|本科累计|专科段|专科累计）。
    首行只要求 累计 >= 本段——官方顶部常是截断桶（「X 分及以上共 N 人」）。
    """
    width = len(rows[0]) if rows else 0
    if width not in (3, 5):
        raise ValueError(f"不支持的列宽: {width}")
    pairs = [(1, 2)] if width == 3 else [(1, 2), (3, 4)]
    prev: list[int | None] = [None] * len(pairs)
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
                if cum < seg:
                    raise ValueError(f"首行累计小于本段: score={score} {seg}>{cum}")
            elif cum != prev[i] + seg:
                raise ValueError(f"累计断裂 score={score}: {prev[i]}+{seg}!={cum}")
            prev[i] = cum
        prev_score = score


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------
def save(doc: dict, out_dir: Path | None = None) -> Path:
    year, prov = doc["meta"]["year"], doc["meta"]["province"]
    d = (out_dir or OUT_DIR) / str(year)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{prov}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return p
