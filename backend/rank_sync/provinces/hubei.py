"""湖北：jyt.hubei.gov.cn（省教育厅）普通高考总分一分一段统计表。

3+1+2，物理/历史分表，**每表独立 PDF**；版式与浙江同构（每页并排 3 组
「分数|人数|累计人数」），但表头是一整行文本而不是三个「总分」格——
公共分块解析器已兼容两种表头。

口径：表内统计人数**含政策性加分**（表头注明），与广东本科档口径不同源，
跨省比较时要注意。
"""
from __future__ import annotations

from ..common import (
    http_get, now_iso, parse_blocked_pdf, sha256, validate_rows,
)

PROVINCE = "湖北"
SITE = "https://jyt.hubei.gov.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

_BASE25 = "https://jyt.hubei.gov.cn/bmdt/ztzl/gxzs/zszy/zsfw/202506"
# 每省每年直接给到 PDF（省教育厅附件链接稳定，不带跳转）
ATTACHMENTS = {
    2025: {
        "物理类": f"{_BASE25}/P020250625730351882018.pdf",
        "历史类": f"{_BASE25}/P020250625730351260572.pdf",
    },
}
# 溯源页：省教育厅「招生服务」栏目（PDF 直链也在其中，但给人看的是这个栏目）
NOTICES = {
    2025: "https://jyt.hubei.gov.cn/bmdt/ztzl/gxzs/zszy/zsfw/",
}

# 缺口的实证原因（不 OCR、不臆造；下一批拿到机读原表再补）
KNOWN_GAPS = {
    2022: "省教育厅「招生资料」栏目（15 页全扫）未见 2022 一分一段通知；市级考试院有 PDF 转载，启用须标 reprint",
    2023: "同上，未找到省级机读原表",
    2024: "通知页正文是 10 张 JPG（W0202406..._ORIGIN.jpg），无表格/附件——不 OCR",
    2026: "省教育考试院通知页同为图片（11 张），无文本层——不 OCR",
}


def parse(year: int) -> dict:
    files = ATTACHMENTS[year]
    subjects: dict = {}
    shas: dict[str, str] = {}
    for subj, url in files.items():
        blob = http_get(url, timeout=180)
        rows, top_note = parse_blocked_pdf(blob)
        validate_rows(rows)
        subjects[subj] = {"rows": rows, "top_note": top_note}
        shas[subj] = sha256(blob)
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": NOTICES[year],
            "attachment_url": files.get("物理类", ""),
            "attachment_sha256": shas.get("物理类", ""),
            "attachment_sha256_map": shas,
            "subject_scheme": SCHEME,
            "note": "统计人数含政策性加分（表头注）；每科类一份 PDF",
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
