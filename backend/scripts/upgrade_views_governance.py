"""内容治理升级（S1）：为每条专业观点补齐治理字段，并去人格化内容框架文案。

幂等：已带 evidence_grade 的条目跳过；可重复运行。
运行：python backend/scripts/upgrade_views_governance.py
"""
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTENT = os.path.join(ROOT, "shared", "content.json")

REVIEWED_AT = "2026-10-20"   # 本次集中复核日期
EXPIRES_AT = "2027-06-30"    # 下一高考季前必须重新复核

# 证据分级：与数据侧 data_source 同为置信度的一维
#   A = 强共识推荐 / 资料充分；B = 条件性（慎选）；C = 高风险规避（需最严复核）
GRADE_BY_VIEW = {"recommend": "A", "caution": "B", "avoid": "C"}


def upgrade(data: dict) -> int:
    majors = data.get("MAJORS", [])
    changed = 0
    for m in majors:
        if m.get("evidence_grade"):
            continue
        m["view_source"] = "张雪峰公开观点（社区整理）"
        m["evidence_grade"] = GRADE_BY_VIEW.get(m.get("view"), "B")
        verify = m.get("verify", "") or ""
        m["source_url"] = verify if verify.startswith("http") else ""
        m["reviewed_at"] = REVIEWED_AT
        m["expires_at"] = EXPIRES_AT
        changed += 1

    cs = data.setdefault("CONTENT_SOURCE", {})
    cs["framework"] = "就业确定性优先（普通家庭 + 就业导向的务实决策方法）"
    cs["view_basis"] = ("就业确定性优先：公开观点（社区整理，非官方，属定性判断）；"
                        "张雪峰为观点来源之一，本产品不以其姓名作品牌背书。")
    cs["note"] = ("每个专业的 source_year 为观点整理年份，source_note 为该大类的证据口径说明；"
                  "现已补齐 view_source / evidence_grade / reviewed_at / expires_at 治理字段，"
                  "每年高考季前需按 pending_views 清单复核。")
    data["NOTE"] = "单一数据源：uni-app 前端与 Python 后端共用。年度更新只改本文件并 bump APP_VERSION。" \
                   "内容来源：公开就业导向观点（社区整理）+ 开源资源核实，仅供学习参考。"
    return changed


def main():
    with open(CONTENT, "r", encoding="utf-8") as f:
        data = json.load(f)
    changed = upgrade(data)
    with open(CONTENT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"content.json 治理升级完成：新增/更新 {changed} 条专业治理字段")


if __name__ == "__main__":
    main()
