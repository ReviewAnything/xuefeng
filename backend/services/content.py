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
