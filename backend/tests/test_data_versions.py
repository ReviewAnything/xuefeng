"""数据版本管理测试：年度更新 / 校验 / 补丁 / 发布 / 回滚 / 审计。"""
import main
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from db import repository as repo
from db import session_scope
from db.models import AdmissionBaseline, DataChange, DataVersion
from services import data_versions as DV

c = TestClient(main.app)

TEST_YEAR = 2099


def _auth() -> dict:
    r = c.post("/api/admin/login", json={"username": "admin", "password": "xuefeng@2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cleanup(year: int = TEST_YEAR) -> None:
    """清理测试年份，避免影响其他用例。"""
    with session_scope() as s:
        s.execute(delete(AdmissionBaseline).where(AdmissionBaseline.year == year))
        s.execute(delete(DataVersion).where(DataVersion.year == year))
        s.execute(delete(DataChange).where(DataChange.year == year))
    DV._invalidate()


def test_active_year_has_published_version():
    j = c.get("/api/admin/versions", headers=_auth()).json()
    assert j["ok"] is True
    assert j["active_year"] >= 2024
    published = [v for v in j["versions"] if v["status"] == "published"]
    assert published and published[0]["year"] == j["active_year"]
    assert published[0]["row_count"] == 280


def test_baselines_are_year_scoped():
    active = repo.active_year()
    rows = repo.baseline_rows(year=active)
    assert len(rows) == 280
    assert {r["year"] for r in rows} == {active}


def test_clone_year_creates_draft_with_carried_rows():
    _cleanup()
    src = repo.active_year()
    r = c.post("/api/admin/versions/clone", json={"from_year": src, "to_year": TEST_YEAR,
                                                  "note": "pytest 年度更新"}, headers=_auth())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["status"] == "draft"
    assert j["version"]["rows"] == 280 and j["version"]["carried_rows"] == 280

    detail = c.get("/api/admin/versions", headers=_auth()).json()
    v = next(x for x in detail["versions"] if x["year"] == TEST_YEAR)
    assert v["status"] != "published"          # 草稿对外不可见
    assert v["is_active"] is False
    assert repo.active_year() == src           # 生效年份未被改变


def test_pending_updates_lists_carried_rows():
    pending = c.get(f"/api/admin/versions/{TEST_YEAR}/pending", headers=_auth()).json()
    assert pending["ok"] is True
    assert pending["total"] == 280
    assert len(pending["provinces"]) == 31


def test_validate_reports_no_error_for_cloned_year():
    j = c.post(f"/api/admin/versions/{TEST_YEAR}/validate", headers=_auth()).json()
    assert j["ok"] is True, j.get("errors")
    assert j["stats"]["rows"] == 280
    # 校验通过后草稿升级为 validated
    v = next(x for x in c.get("/api/admin/versions", headers=_auth()).json()["versions"]
             if x["year"] == TEST_YEAR)
    assert v["status"] in ("validated", "published")


def test_patch_records_field_level_audit_and_undo():
    with session_scope() as s:
        row = s.scalar(select(AdmissionBaseline).where(
            AdmissionBaseline.year == TEST_YEAR, AdmissionBaseline.province == "河南",
            AdmissionBaseline.subject == "物理类", AdmissionBaseline.tier == "普通一本"))
        row_id, old_rank = row.id, row.min_rank

    r = c.patch(f"/api/admin/baselines/{row_id}",
                json={"min_rank": old_rank + 1000, "source_year": TEST_YEAR,
                      "reason": "pytest 补丁"}, headers=_auth())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["row"]["min_rank"] == old_rank + 1000
    assert any(ch["field"] == "min_rank" for ch in j["changes"])

    changes = c.get("/api/admin/changes", params={"year": TEST_YEAR}, headers=_auth()).json()["rows"]
    change = next(x for x in changes if x["field"] == "min_rank" and x["action"] == "patch")
    assert change["old_value"] == str(old_rank) and change["new_value"] == str(old_rank + 1000)
    assert change["operator"] == "admin"

    undo = c.post(f"/api/admin/changes/{change['id']}/undo", headers=_auth())
    assert undo.status_code == 200, undo.text
    assert undo.json()["row"]["min_rank"] == old_rank


def test_publish_switches_active_year_and_rollback_restores():
    src = repo.active_year()
    pub = c.post(f"/api/admin/versions/{TEST_YEAR}/publish", headers=_auth())
    assert pub.status_code == 200, pub.text
    assert pub.json()["previous"] == src
    assert repo.active_year() == TEST_YEAR

    back = c.post(f"/api/admin/versions/{src}/rollback", headers=_auth())
    assert back.status_code == 200, back.text
    assert repo.active_year() == src
    versions = {v["year"]: v["status"] for v in DV.list_versions()}
    assert versions[src] == "published" and versions[TEST_YEAR] == "archived"
    _cleanup()


def test_versions_require_auth():
    assert c.get("/api/admin/versions").status_code == 401
    assert c.post("/api/admin/versions/clone", json={"from_year": 2026, "to_year": 2098}).status_code == 401
