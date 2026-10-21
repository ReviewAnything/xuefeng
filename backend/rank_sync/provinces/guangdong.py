"""广东：eea.gd.gov.cn 普通类（物理/历史）分数段统计表。

版式三年三变（都已踩过）：
- 2024/2025：ZIP 打包两份 PDF；
- 2022/2026：逐类 PDF，锚文本带类名；
- 2023：单个「下载附件」合并 PDF——**85 页扫描件，无文本层**，按纪律缺省不 OCR
  （已移出 NOTICES，见下方 KNOWN_GAPS；第三方仅单轨，与双档位口径不合，不混入）。
双档位：本科累计与专科累计是两套位次（本科/专科层次加分不同），不能混用。
"""
from __future__ import annotations

import io
import zipfile

from ..common import (
    find_attachments, http_get, now_iso, parse_gd_pdf, sha256, validate_rows,
)

PROVINCE = "广东"
SITE = "https://eea.gd.gov.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

NOTICES = {
    2026: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4916195.html",
    2025: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4734449.html",
    2024: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_4445715.html",
    2022: "https://eea.gd.gov.cn/zwgk_tjxx/content/post_3986282.html",
}
# 2023 官方附件是 85 页扫描件（无文本层），按纪律不 OCR。
# 第三方（eol.cn）2023 有文本表，但只有**单轨 3 列**；广东是双档位省
# （本科/专科加分位次不同），把单轨镜像成两档等于伪造专科位次，故不混入——
# 宁缺勿假。曾一度把 2023 留在 NOTICES 里，导致全量 sync 每年稳定 FAIL 一条，
# 现移出 NOTICES：不再作为期望年份去尝试，原因登记在此。
KNOWN_GAPS = {
    2023: ("附件为 85 页扫描件（无文本层），按纪律不 OCR；第三方仅单轨 3 列，"
           "与广东双档位（本科/专科）口径不一致，镜像会伪造专科位次，故不取"),
}


def subject_of(label: str) -> str | None:
    """附件标签 -> 科类。只收普通类物理/历史（体育艺术类不要）。"""
    if ("普通类" in label or "普通" in label) and "分数段" in label:
        if "物理" in label:
            return "物理类"
        if "历史" in label:
            return "历史类"
    return None


def _sniff_subject(pdf_bytes: bytes) -> str | None:
    """无名合并 PDF：从首页文本嗅探含哪些科类标题（2023 形态）。"""
    from pdfminer.high_level import extract_text
    import pathlib
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        p = f.name
    try:
        head = extract_text(p, page_numbers=[0, 1]) or ""
    finally:
        pathlib.Path(p).unlink(missing_ok=True)
    found = [s for s in ("物理类", "历史类") if s[0] in head and "分数段" in head]
    return "合并" if len(found) > 1 else (found[0] if found else None)


def parse(year: int) -> dict:
    notice_url = NOTICES[year]
    atts = find_attachments(notice_url, kinds="zip|pdf")
    subjects: dict = {}
    meta_bits: dict[str, str] = {}

    def consume(blob: bytes, att_url: str, subj: str):
        rows, top_note = parse_gd_pdf(blob)
        validate_rows(rows)
        subjects[subj] = {"rows": rows, "top_note": top_note}
        meta_bits[subj + "_sha"] = sha256(blob)
        meta_bits[subj + "_url"] = att_url

    zips = [a for a in atts if a["kind"] == "zip"]
    if zips:
        blob = http_get(zips[0]["url"], timeout=120)
        meta_bits["zip"] = sha256(blob)
        meta_bits["zip_url"] = zips[0]["url"]
        zf = zipfile.ZipFile(io.BytesIO(blob))
        for info in zf.infolist():
            if info.is_dir():
                continue
            subj = subject_of(info.filename)
            if subj:
                consume(zf.read(info), zips[0]["url"], subj)
    pdfs = [a for a in atts if a["kind"] == "pdf"]
    for a in pdfs:
        subj = subject_of(a["label"])
        if not subj:
            continue
        consume(http_get(a["url"], timeout=120), a["url"], subj)
    if not subjects:  # 无锚文本类名：下载嗅探
        for a in pdfs:
            blob = http_get(a["url"], timeout=180)
            kind = _sniff_subject(blob)
            if kind in ("物理类", "历史类"):
                consume(blob, a["url"], kind)
    if not subjects:
        raise ValueError(f"未能取到普通类 物理/历史 数据: {[a['label'] for a in atts]}")
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": notice_url, "subject_scheme": SCHEME,
            "attachment_url": meta_bits.get("zip_url") or meta_bits.get("物理类_url", ""),
            "attachment_sha256": meta_bits.get("zip") or meta_bits.get("物理类_sha", ""),
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
