"""读取单一数据源 shared/content.json（前端与后端共用）。"""
import json
import os

_SHARED = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "content.json")


def load_content() -> dict:
    with open(os.path.abspath(_SHARED), "r", encoding="utf-8") as f:
        return json.load(f)


CONTENT = load_content()

MAJORS = CONTENT["MAJORS"]
RESOURCES = CONTENT["RESOURCES"]
QUESTIONS = CONTENT["QUESTIONS"]
APP_VERSION = CONTENT.get("APP_VERSION", "2.0.0")
DATA_DATE = CONTENT.get("DATA_DATE", "")
# 内容可溯：观点整理年份/证据口径（每个专业另带 source_year / source_note）
CONTENT_SOURCE = CONTENT.get("CONTENT_SOURCE", {})

# 视图标签映射
VIEW_LABEL = {"recommend": "推荐", "caution": "慎选", "avoid": "避坑"}

# ---------------------------------------------------------------- 内容治理（S1）

from datetime import date, datetime, timezone  # noqa: E402  (置于常量之后)


def evidence_grade_of(major: dict) -> str:
    """观点证据分级（A/B/C）：与数据侧 data_source 同为置信度的一维。"""
    return major.get("evidence_grade", "") or ""


def pending_reviews(today: str | None = None) -> int:
    """待复核观点数：缺证据分级 / 缺观点来源 / 复核过期 / 未登记复核日期。

    每年高考季前需把待复核清单清零——这是差异化资产（观点表）的最小治理护栏，
    防止「分数年年更新、观点原地不动」导致的静默失真。
    """
    today = today or date.today().isoformat()
    n = 0
    for m in MAJORS:
        if not m.get("evidence_grade"):
            n += 1
            continue
        if not m.get("view_source"):
            n += 1
            continue
        exp = m.get("expires_at")
        if exp and exp < today:
            n += 1
            continue
        if not m.get("reviewed_at"):
            n += 1
    return n


def validate_content() -> dict:
    """内容治理校验：与 ``admission_baselines`` 同口径的轻量版本。

    content 不在 DB 表里（单一 JSON 数据源），故独立于 data_versions 表实现，
    但产出同形（ok/errors/warnings/stats）的结果，便于管理端复用。
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    today = date.today().isoformat()
    missing_grade = [m["name"] for m in MAJORS if not m.get("evidence_grade")]
    if missing_grade:
        errors.append({"code": "EVIDENCE_GRADE",
                       "message": f"{len(missing_grade)} 个专业缺 evidence_grade",
                       "sample": missing_grade[:12]})
    missing_src = [m["name"] for m in MAJORS if not m.get("view_source")]
    if missing_src:
        errors.append({"code": "VIEW_SOURCE",
                       "message": f"{len(missing_src)} 个专业缺 view_source",
                       "sample": missing_src[:12]})
    expired = [m["name"] for m in MAJORS if m.get("expires_at") and m["expires_at"] < today]
    if expired:
        warnings.append({"code": "REVIEW_EXPIRED",
                         "message": f"{len(expired)} 个专业复核已过期（expires_at 早于今天）",
                         "sample": expired[:12]})
    not_reviewed = [m["name"] for m in MAJORS if not m.get("reviewed_at")]
    if not_reviewed:
        warnings.append({"code": "NOT_REVIEWED",
                         "message": f"{len(not_reviewed)} 个专业未登记复核日期",
                         "sample": not_reviewed[:12]})
    return {
        "ok": not errors, "errors": errors, "warnings": warnings,
        "stats": {"majors": len(MAJORS), "pending": pending_reviews(today)},
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
