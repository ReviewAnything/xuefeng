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
import time
from datetime import datetime, timezone
from html import unescape
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


_BAD_BODY_PAT = re.compile(rb"<title>\s*404 Not Found|nginx/\d|Access Denied|Bad Gateway", re.I)


def _is_error_page(blob: bytes) -> bool:
    """识别「HTTP 200 但内容其实是错误页」——省站限流时就这么回。

    实测 hneeb.cn 在连续抓取时会回一个 555 字节的 nginx 404 页面，
    ``requests`` 看到的是 200 + 正常 content，静默当成正文会解析出 0 行。
    """
    return len(blob) < 2048 and bool(_BAD_BODY_PAT.search(blob))


def http_get(url: str, timeout: int = 60, retries: int = 4) -> bytes:
    """抓取（带重试 + 退避 + curl 兜底）。

    省站普遍有两类抖动，都必须重试而不是把错误页当正文：
    1. 偶发 555 字节 404 页（限流，HTTP 200 但内容不是正文）；
    2. TLS 握手失败 / 连接重置（证书链与 requests 不兼容，curl 可以）。
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            if not _is_error_page(r.content):
                return r.content
            last = RuntimeError(f"站点返回错误页（{len(r.content)} 字节）: {url}")
        except (requests.exceptions.SSLError,
                requests.exceptions.ConnectionError) as exc:
            # 证书链不兼容 / 连接被重置（TLS 指纹差异）都走 curl 兜底
            try:
                blob = _curl_get(url, timeout)
                if not _is_error_page(blob):
                    return blob
                last = RuntimeError(f"站点返回错误页（curl, {len(blob)} 字节）: {url}")
            except Exception:
                last = exc
        except requests.exceptions.HTTPError as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(0.8 * (attempt + 1))  # 线性退避，别把限流打成封禁
    raise last if last else RuntimeError(f"抓取失败: {url}")


_CHARSET_PAT = re.compile(rb'charset\s*=\s*["\']?([\w-]+)', re.I)
# 声明名 -> 实际解码器（gb2312/gbk 是 gb18030 子集，统一用超集最稳）
_ENC_ALIAS = {"gb2312": "gb18030", "gbk": "gb18030", "gb18030": "gb18030",
              "utf8": "utf-8", "utf-8": "utf-8", "big5": "big5"}


def decode_html(blob: bytes) -> str:
    """省站编码混乱（UTF-8 / GBK 都有），按「严格解码」择优。

    不能靠替换字符计数：``gbk`` 解 UTF-8 字节、``utf-8`` 解 GBK 字节都可能
    "成功"产出无 U+FFFD 的乱码（尤其 errors="ignore" 会静默丢字节，
    让 ``累计`` 变成 ``ۼ``）。所以只认严格解码成功的结果，且优先信
    ``<meta charset>`` 的声明（湖南站是 GBK）。
    """
    m = _CHARSET_PAT.search(blob[:4096])
    declared = _ENC_ALIAS.get(m.group(1).decode("ascii", "ignore").lower()) if m else None
    order = ([declared] if declared else []) + ["utf-8", "gb18030"]
    for enc in dict.fromkeys(order):
        try:
            return blob.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # 全部严格失败才退化（保留替换字符，便于上层发现异常）
    return blob.decode(declared or "gb18030", "replace")


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
def parse_html_table(html: str, tracks: bool = False):
    """从 HTML 表格取 [score, seg, cum]。表尾「N 分以下」桶不计入 rows，
    作为 below_bucket 返回（它不是某个具体分数，混进 rows 会让位次失真）。

    两种列宽都要支持（湖南自身就跨年变了口径）：
    - 3 列 ``档分|本段|累计``（2025/2026，表头写「含优惠加分」）；
    - 5 列 ``档分|本段|累计|本段|累计``（2022–2024，双轨：含全国性加分 /
      含全国性和地方性加分）。双轨的**主轨取含全国性加分**（投档位次口径），
      地方性加分那一轨另存，不混进主轨——它只对省属高校生效，混用会低估位次。

    ``tracks=True`` 时返回 4 元组，第 4 项为 ``{"label", "rows"}`` 或 None。

    坑：湖南 2025 的源表把「100 以下」这一行的首格也印成 ``100``（与上一行同分），
    只靠文本分不出来。判据是结构性的——**末行与上一行同分，且 累计=前项+本段**，
    那它就是「N 分以下」合计桶（真实分数不会出现两行同分）。
    """
    singles: list[list[int]] = []
    duals: list[list[int]] = []
    below: dict | None = None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [
            # &nbsp; 是实体不是空白字符，必须先 unescape 再压空白，
            # 否则「657&nbsp;」既过不了 fullmatch 也过不了 isdigit（江苏 2025 历史）。
            re.sub(r"\s+", "", unescape(re.sub(r"<[^>]+>", "", c)))
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        ]
        m = re.fullmatch(r"(\d{3})", cells[0]) if cells else None
        if not m and cells:
            # 官方常把关键批次线所在行标注成「520（特招线）」「441（本科线）」，
            # 严格 fullmatch 会整行丢掉 -> 累计链断裂（福建 2025 就断在 520）。
            # 取前导三位整数即可；纯区间行（如「689-750」）仍按顶部截断桶处理。
            if not re.search(r"\d\s*[-—~－]\s*\d", cells[0]):
                m = re.fullmatch(r"(\d{3})\D.*", cells[0])
        mb = re.fullmatch(r"(\d{3})分?以下", cells[0]) if cells else None
        if m:
            nums = cells[1:]
            if len(nums) == 2 and all(n.isdigit() for n in nums):
                singles.append([int(m.group(1)), int(nums[0]), int(nums[1])])
                continue
            if len(nums) == 4 and all(n.isdigit() for n in nums):
                duals.append([int(m.group(1))] + [int(n) for n in nums])
                continue
        if mb:
            nums = cells[1:]
            if len(nums) in (2, 4) and all(n.isdigit() for n in nums):
                below = {"score_below": int(mb.group(1)),
                         "seg": int(nums[0]), "cum": int(nums[1])}
    # 双轨优先：同一页不会两种列宽并存（除非源站改版留下脏行）
    if duals and len(duals) >= len(singles):
        primary = [[r[0], r[1], r[2]] for r in duals]
        alt = {"label": "含全国性和地方性加分",
               "rows": [[r[0], r[3], r[4]] for r in duals]}
        rows = primary
    else:
        rows, alt = singles, None
    if not rows:
        raise ValueError("HTML 表格未解析出任何数据行")
    # 末行与上一行同分且累计能接上 -> 「N 分以下」合计桶
    if (len(rows) >= 2 and rows[-1][0] == rows[-2][0]
            and rows[-1][2] == rows[-2][2] + rows[-1][1]):
        last = rows.pop()
        if alt:
            alt["rows"].pop()
        below = below or {"score_below": last[0], "seg": last[1], "cum": last[2]}
    # 顶部截断桶：首行 累计 > 本段 说明该分之上还有被合并统计的考生
    # （官方常印成「X 分及以上共 N 人」）。相等则是顶分单独一行，不需要备注。
    top_note = f"{rows[0][0]}↑" if rows[0][2] > rows[0][1] else ""
    if tracks:
        return rows, top_note, below, alt
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
# 组装：第三方文本转录页 -> doc
# ---------------------------------------------------------------------------
def doc_from_html_pages(province: str, year: int, pages: dict[str, str], *,
                        scheme: str, data_source: str, note: str,
                        source_url: str | None = None) -> dict:
    """按 ``{科类: 文章 URL}`` 逐个抓 HTML 表格，强校验通过后组装成 doc。

    第三方文本转录省（如 gaokao.eol.cn）形态一致：单栏 ``<tr><td>`` 三列
    ``分数 | 人数 | 累计人数``。纪律与官方管线完全相同——解析在内存完成，
    任一科类校验不过就整份拒收，绝不落半份。
    """
    subjects: dict = {}
    for subj, url in pages.items():
        html_src = http_get_html(url, timeout=60)
        rows, top, below = parse_html_table(html_src)
        validate_rows(rows)
        blk: dict = {"rows": rows, "source_url": url}
        if top:
            blk["top_note"] = top
        if below:
            blk["below_bucket"] = below
        subjects[subj] = blk
    return {
        "meta": {
            "year": year,
            "province": province,
            "data_source": data_source,
            "source_url": source_url or next(iter(pages.values())),
            "subject_scheme": scheme,
            "note": note,
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }


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
