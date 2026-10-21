"""广西：gxeea.cn（广西招生考试院）「一分一档表」。

广西不发正文表格、也不发附件，而是**每年开一个独立子站**：
``/{年度}yfyd/index.html``（2024/2026）或 ``/{年度}gxyfyd/index.html``（2025），
索引页里挂 88 条链接（物理/历史 × 两种加分口径 × 普通/国家专项 × 各艺术体育类别），
每条点进去是**服务端直出的 HTML 表格**（4 列，见下）。

版式（三年一致，2026-10 核对）::

    说明：总分=总成绩+全国性加分；人数、累计人数、名次统计均不包含已确定录取的考生。
    总分 | 人数 | 累计人数 | 名次
     687 |   2  |   14     |  13

- 第 4 列 ``名次`` 是**派生值** = ``累计 − 人数 + 1``（本分段的头名位次）。12 张表
  逐行核过，无一例外——所以把它当**交叉校验**用：任一行对不上就整份拒收，
  免得列错位时还静默落盘。
- 顶部是截断桶：首行 ``累计 > 人数``（687 的 14 人里有 12 人分数更高但没单独列出），
  ``名次`` 直接给出被截断掉的人数。
- **0 人的分段不印**（2025 物理缺 685、2024 历史缺 669/664、2026 历史缺 671/668），
  累计链照样接得上，缺口记进 ``omitted_scores``。
- 分数下限按年不同：2024/2025 止于 **200**，2026 止于 **180**。低于下限的人
  官方不公布，``score_floor`` 如实记源表末行分数。

两条**加分轨**（同一科类两份表，唯一差别是加不加以地方性加分）：

- ``_qg``「总分=总成绩+**全国性**加分」——**主轨**，与湖南/其它省口径一致，
  进 ``subjects[].rows``；
- ``_qn``「总分=总成绩+全国性加分和**地方性**加分的最高分」——副轨，单存
  ``subjects[].alt_track``，不参与位次计算。地方性加分只对区内院校投档生效，
  混用会把位次算低（湖南同款处理）。

**同一索引页里的其它 84 条链接一律不并入**：国家专项计划（``_zx``：仅面向
资格考生，累计人数是子集）、体育（``_1_tiyu``/``_2_tiyu``）、美术/书法/音乐/
舞蹈/播音/表导演（综合分表，不是文化总分）。

2022/2023 的年度子站已下线（``/2022yfyd/``、``/2022gxyfyd/``、``/2023yfyd/``、
``/2023gxyfyd/`` 全部 404，数据页 URL 直连同样 404），栏目页只剩艺术统考的一分一档；
第三方站点虽有转录但非官方，按纪律**不落盘**，在 ``KNOWN_GAPS`` 里写明原因。
"""
from __future__ import annotations

import html as ht
import re
from urllib.parse import urljoin

from ..common import (
    decode_html, http_get, http_get_html, now_iso, sha256, validate_rows,
)

PROVINCE = "广西"
SITE = "https://www.gxeea.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

# 子站目录名不统一：2024/2026 是 {年}yfyd，2025 是 {年}gxyfyd。两条都要试。
_DIR_PATTERNS = ("{year}yfyd", "{year}gxyfyd")
_FILE_PAT = "{year}_yifenyidang_{slug}_{track}.html"

SOURCES = {
    2024: {
        "index": SITE + "/2024yfyd/index.html",
        "files": {"物理类": SITE + "/2024yfyd/yifenyidang/2024_yifenyidang_wuli_qg.html",
                  "历史类": SITE + "/2024yfyd/yifenyidang/2024_yifenyidang_lishi_qg.html"},
        "alt": {"物理类": SITE + "/2024yfyd/yifenyidang/2024_yifenyidang_wuli_qn.html",
                "历史类": SITE + "/2024yfyd/yifenyidang/2024_yifenyidang_lishi_qn.html"},
    },
    2025: {
        "index": SITE + "/2025gxyfyd/index.html",
        "files": {"物理类": SITE + "/2025gxyfyd/yifenyidang/2025_yifenyidang_wuli_qg.html",
                  "历史类": SITE + "/2025gxyfyd/yifenyidang/2025_yifenyidang_lishi_qg.html"},
        "alt": {"物理类": SITE + "/2025gxyfyd/yifenyidang/2025_yifenyidang_wuli_qn.html",
                "历史类": SITE + "/2025gxyfyd/yifenyidang/2025_yifenyidang_lishi_qn.html"},
    },
    2026: {
        "index": SITE + "/2026yfyd/index.html",
        "files": {"物理类": SITE + "/2026yfyd/yifenyidang/2026_yifenyidang_wuli_qg.html",
                  "历史类": SITE + "/2026yfyd/yifenyidang/2026_yifenyidang_lishi_qg.html"},
        "alt": {"物理类": SITE + "/2026yfyd/yifenyidang/2026_yifenyidang_wuli_qn.html",
                "历史类": SITE + "/2026yfyd/yifenyidang/2026_yifenyidang_lishi_qn.html"},
    },
}

KNOWN_GAPS = {
    2022: "年度一分一档子站已下线（/2022yfyd/、/2022gxyfyd/ 及数据页均 404），"
          "通知公告/招生信息栏目未收录普通高考一分一档；第三方转录非官方，不落盘",
    2023: "同上（/2023yfyd/、/2023gxyfyd/ 及数据页均 404）",
}

# 科类词：物理/历史（2024 起 3+1+2）；老口径「理工/文史」留给未来可能补的年份
SUBJECT_OF = {"wuli": "物理类", "lishi": "历史类"}
TITLE_PAT = re.compile(r"^(\d{4})年(物理类|历史类)一分一档表")
# 索引页里要挡掉的类别：国家专项、体育、艺术各类综合分
AUX_PAT = re.compile(r"_zx|_1_tiyu|_2_tiyu|meishu|shufa|yinyue|wudao|boyin|"
                     r"yinshi|fuzhuang|国家专项|体育|美术|书法|音乐|舞蹈|播音|表\(导\)演")
TRACK_OF = {"qg": "全国性加分", "qn": "全国性加分和地方性加分的最高分"}
HEADER = ("总分", "人数", "累计人数", "名次")


# ---------------------------------------------------------------------------
# 解析（纯函数，便于脱网单测）
# ---------------------------------------------------------------------------
def _cells_of(tr: str) -> list[str]:
    return [re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c))
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]


def parse_table(html: str) -> dict:
    """4 列表格 -> {rows, title, note, rank_checked}。

    ``rows`` 是 ``[总分, 人数, 累计人数]``（第 4 列名次不落盘，只做校验：
    名次必须恒等于 ``累计 − 人数 + 1``）。
    """
    title = ""
    m = re.search(r'<div[^>]*class="STYLE4"[^>]*>(.*?)</div>', html, re.S)
    if m:
        title = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", m.group(1)))
    rows: list[list[int]] = []
    note = ""
    checked = 0
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = _cells_of(tr)
        if not cells:
            continue
        if not rows and not note and cells[0].startswith("说明"):
            note = cells[0]
            continue
        if cells[:4] == list(HEADER):
            continue
        if len(cells) != 4 or not all(c.isdigit() for c in cells):
            continue
        score, seg, cum, rank = (int(c) for c in cells)
        if not (0 <= score <= 750):
            raise ValueError(f"分数越界: {score}")
        # 名次是派生列，对不上说明这一行列错位了——不能只信前三列
        if rank != cum - seg + 1:
            raise ValueError(
                f"名次列不自洽（{score} 分）：名次={rank} != 累计{cum}-人数{seg}+1")
        rows.append([score, seg, cum])
        checked += 1
    if not rows:
        raise ValueError("广西一分一档页未解析出任何数据行")
    validate_rows(rows)
    return {"rows": rows, "title": title, "note": note, "rank_checked": checked}


def top_note_of(rows: list[list[int]]) -> str:
    """顶行 ``累计 > 人数`` 说明该分之上还有人没单列（官方只印「X 分及以上」合计）。"""
    return f"{rows[0][0]}↑" if rows[0][2] > rows[0][1] else ""


def omitted_scores(rows: list[list[int]]) -> list[int]:
    """表内 0 人未印的分段（累计链依旧是接得上的）。"""
    seen = {r[0] for r in rows}
    return [s for s in range(rows[0][0], rows[-1][0], -1) if s not in seen]


def subject_of_title(title: str) -> str:
    if "物理" in title:
        return "物理类"
    if "历史" in title:
        return "历史类"
    raise ValueError(f"广西表名无法判定科类：{title!r}")


def title_ok(title: str, year: int) -> bool:
    """表名守卫：必须是该年该科类的**普通**一分一档表（艺术/体育/专项另有一套）。"""
    if AUX_PAT.search(title) or "国家专项" in title:
        return False
    m = TITLE_PAT.match(title)
    return bool(m) and int(m.group(1)) == year


# ---------------------------------------------------------------------------
# 索引页发现
# ---------------------------------------------------------------------------
def parse_anchors(html: str) -> list[tuple[str, str]]:
    """索引页 -> [(href, 链接文字)]。

    坑：href 用**反斜杠**当目录分隔符（``yifenyidang\\2025_yifenyidang_wuli_qg.html``），
    直接 ``urljoin`` 会拼出一个不存在的 URL，必须先替换成 ``/``。
    """
    out: list[tuple[str, str]] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href = ht.unescape(m.group(1)).replace("\\", "/").strip()
        text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", m.group(2)))
        if href:
            out.append((href, text))
    return out


def pick_files(pairs: list[tuple[str, str]], year: int) -> dict[str, dict[str, str]]:
    """从索引页链接里挑出两科 × 两轨共 4 条（纯函数）。

    判据是**文件名后缀**（``_wuli_qg`` / ``_lishi_qn``），不是链接文字——文字里
    「国家专项计划历史类…」也含「历史类」，靠文字选会把专项表选进来。
    """
    out: dict[str, dict[str, str]] = {"files": {}, "alt": {}}
    for href, text in pairs:
        low = href.lower()
        if not low.endswith(".html"):
            continue
        m = re.search(r"_(wuli|lishi)_(qg|qn)$", low.rsplit(".", 1)[0].split("/")[-1])
        if not m:
            continue
        if AUX_PAT.search(low):
            continue
        subj = SUBJECT_OF[m.group(1)]
        bucket = "files" if m.group(2) == "qg" else "alt"
        out[bucket].setdefault(subj, href)
    for bucket in ("files", "alt"):
        missing = [s for s in SUBJECTS if s not in out[bucket]]
        if missing:
            raise ValueError(f"广西 {year} 索引页缺链接（{bucket}）：{missing}")
    return out


def index_url(year: int) -> str:
    """子站目录名逐年漂，两条规则都探一遍（HEAD 不行就 GET 看长度）。"""
    last: Exception | None = None
    for pat in _DIR_PATTERNS:
        url = f"{SITE}/{pat.format(year=year)}/index.html"
        try:
            html = http_get_html(url)
        except Exception as exc:      # noqa: BLE001 - 404 就换下一个规则
            last = exc
            continue
        if "yifenyidang" in html:
            return url
    raise ValueError(f"广西 {year} 一分一档子站未找到（试过 {_DIR_PATTERNS}）: {last}")


def discover(year: int) -> dict:
    """该年索引页 + 4 条数据页 URL（新增年份时用它校正 SOURCES）。"""
    idx = index_url(year)
    pairs = parse_anchors(http_get_html(idx))
    picked = pick_files(pairs, year)
    return {
        "index": idx,
        "files": {s: urljoin(idx, u) for s, u in picked["files"].items()},
        "alt": {s: urljoin(idx, u) for s, u in picked["alt"].items()},
    }


def source(year: int) -> dict:
    return SOURCES.get(year) or discover(year)


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------
def _fetch(url: str, subj: str, year: int) -> tuple[dict, str]:
    blob = http_get(url, timeout=120)
    got = parse_table(decode_html(blob))
    title = got["title"]
    if not title_ok(title, year):
        raise ValueError(f"广西 {year} 页面不是普通类一分一档表（表名：{title!r}），拒收")
    if subject_of_title(title) != subj:
        raise ValueError(f"广西 {year} 科类不符：期望 {subj}，表名 {title!r}")
    return got, sha256(blob)


def _track_block(got: dict, label: str | None = None) -> dict:
    """一条加分轨的落盘块。``label`` 只给副轨（主轨的口径写在 ``meta.tracks``）。"""
    rows = got["rows"]
    blk = {
        "rows": rows,
        "total": rows[-1][2],
        "top_note": top_note_of(rows),
        "score_floor": rows[-1][0],
        "omitted_scores": omitted_scores(rows),
    }
    if label:
        blk["label"] = label
    return blk


def parse(year: int) -> dict:
    src = source(year)
    subjects: dict = {}
    shas: dict[str, str] = {}
    urls: dict[str, str] = {}
    alt_urls: dict[str, str] = {}
    alt_shas: dict[str, str] = {}
    notes: dict[str, str] = {}
    for subj in SUBJECTS:
        url = src["files"][subj]
        got, sha = _fetch(url, subj, year)
        blk = _track_block(got)
        blk["table_title"] = got["title"]
        subjects[subj] = blk
        shas[subj], urls[subj] = sha, url
        if got["note"]:
            notes[subj] = got["note"]

        alt_url = (src.get("alt") or {}).get(subj)
        if alt_url:
            alt_got, alt_sha = _fetch(alt_url, subj, year)
            subjects[subj]["alt_track"] = _track_block(alt_got, TRACK_OF["qn"])
            alt_urls[subj], alt_shas[subj] = alt_url, alt_sha

    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": src.get("index") or urls.get("物理类", ""),
        "source_url_map": urls,
        "alt_source_url_map": alt_urls,
        # 页面是服务端直出表格、没有附件：内容固定用**页面字节哈希**
        "source_sha256": shas.get("物理类", ""),
        "source_sha256_map": shas,
        "alt_source_sha256_map": alt_shas,
        "subject_scheme": SCHEME,
        "columns": 3,
        "tracks": {"primary": f"总分=总成绩+{TRACK_OF['qg']}",
                   "alt": f"总分=总成绩+{TRACK_OF['qn']}"},
        "note": ("服务端直出 HTML 四列表（总分|人数|累计人数|名次），名次=累计−人数+1 "
                 "逐行校验；0 人分段不印；主轨取「总分=总成绩+全国性加分」，"
                 "地方性加分轨单列 alt_track；国家专项/体育/艺术综合分表不并入；"
                 "官方注明「人数、累计人数、名次统计均不包含已确定录取的考生」"),
        "published_note": next(iter(notes.values()), ""),
        "score_floor": {s: v["score_floor"] for s, v in subjects.items()},
        "fetched_at": now_iso(),
    }
    if year in KNOWN_GAPS:
        meta["known_gap"] = KNOWN_GAPS[year]
    return {"meta": meta, "subjects": subjects}
