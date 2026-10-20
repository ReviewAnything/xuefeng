"""alignment 证据门槛测试（S7-C）。

S2 让 alignment 从「查表」变成可计算的「可及性核验」，但有个隐藏问题：
只要该 (省/科类) 有校线就能给出「数据支持 / 数据反驳」——哪怕只有两三条。
对置版式（观点 vs 数据）看起来很对称，实际上那句判断**没有信息量**：
样本太薄时它既不能支持也不能反驳，只是把「够不够」说成「值不值」的放大。

S7-C 的做法是**证据门槛 + 单侧降级**：
样本量过门槛才给强判断，否则一律退到 unverified 并写清「为什么不敢判」。
只降级、不升级——证据不足永远往 unverified 退，绝不反向推出「观点成立」。

用例用年份 2096 + 西藏（该省/科类无其它校线）构造薄样本场景，用完即清理。
"""
import main
from fastapi.testclient import TestClient
from sqlalchemy import delete

from db import session_scope
from db.models import SchoolLine
from services import school_lines as SL
from services import verify as V

c = TestClient(main.app)

THIN_YEAR = 2096
THIN_PROVINCE = "西藏"      # 该省在测试库里没有任何校线，适合构造薄样本
THIN_SUBJECT = "物理类"


def _cleanup_thin():
    with session_scope() as s:
        s.execute(delete(SchoolLine).where(SchoolLine.year == THIN_YEAR))
    SL.invalidate_cache()


def _seed_thin(n: int = 3):
    """在「无校线」的省/科类下放 n 条校线（覆盖 n 所院校）。"""
    _cleanup_thin()
    names = ["郑州大学", "河南大学", "河南科技大学", "河南师范大学", "河南理工大学"]
    with session_scope() as s:
        for i in range(n):
            s.add(SchoolLine(year=THIN_YEAR, province=THIN_PROVINCE, subject=THIN_SUBJECT,
                             batch="本科一批", university=names[i % len(names)],
                             university_input=names[i % len(names)], group_code=f"{i:02d}",
                             min_score=500 + i, min_rank=10000 + i * 1000,
                             data_source="estimated_real", match_method="exact",
                             source_url="https://example.edu.cn/thin", note="薄样本测试"))
    SL.invalidate_cache()


def test_evidence_gate_thresholds_are_declared():
    assert V.MIN_EVIDENCE_LINES >= 5 and V.MIN_EVIDENCE_SCHOOLS >= 3


def test_alignment_downgrades_when_evidence_thin():
    """样本太薄 → 单侧降级为 unverified，而不是硬说「支持 / 反驳」。"""
    _seed_thin(3)
    try:
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 20000)
        assert real is not None and real["total_lines"] == 3
        passed, basis = V._evidence_gate(real)
        assert passed is False
        assert basis["gate_passed"] is False
        assert basis["total_lines"] == 3 and basis["total_schools"] == 3

        alignment, label, msg, _raw, got_basis = V._alignment_of("recommend", real)
        assert alignment == "unverified", "样本不足时必须降级，不能给出强判断"
        assert "不下判断" in msg
        assert got_basis["gate_passed"] is False
    finally:
        _cleanup_thin()


def test_alignment_strong_only_when_gate_passed():
    """样本足够时才允许 supported / refuted，且依据随结果返回。"""
    _seed_thin(12)          # 12 条 / 5 所 → 过门槛
    try:
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 20000)
        passed, basis = V._evidence_gate(real)
        assert passed is True
        assert basis["total_lines"] == 12

        alignment, _label, _msg, _raw, got_basis = V._alignment_of("recommend", real)
        assert alignment in ("supported", "refuted")
        assert got_basis["gate_passed"] is True
        assert got_basis["min_lines"] == V.MIN_EVIDENCE_LINES
        assert got_basis["grade_label"], "依据里必须带数据等级（官方 / 真实抓取）"
    finally:
        _cleanup_thin()


def test_alignment_never_invents_conflict():
    """红线：无论样本厚薄，alignment 都不出现 conflict / aligned。"""
    for n in (0, 3, 12):
        _seed_thin(n) if n else _cleanup_thin()
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 20000)
        alignment, _l, _m, _r, _b = V._alignment_of("avoid", real)
        assert alignment in ("supported", "refuted", "unverified")
    _cleanup_thin()


def _seed_distinct(n: int, rank_base: int = 10000):
    """放 n 条**互不重名**的校线（覆盖 n 所院校），用于验证「院校数」维度的门槛。"""
    _cleanup_thin()
    with session_scope() as s:
        for i in range(n):
            s.add(SchoolLine(year=THIN_YEAR, province=THIN_PROVINCE, subject=THIN_SUBJECT,
                             batch="本科一批", university=f"薄样本大学{i:02d}",
                             university_input=f"薄样本大学{i:02d}", group_code=f"{i:02d}",
                             min_score=500 + (i % 100), min_rank=rank_base + i * 1000,
                             data_source="estimated_real", match_method="exact",
                             source_url="https://example.edu.cn/band", note="分层门槛测试"))
    SL.invalidate_cache()


def test_evidence_band_none_thin_full():
    """S8-B：三档分层——近乎无样本 / 偏薄 / 充足，各自的处理不同。"""
    # none：2 条 → 连方向性事实都不给
    _seed_thin(2)
    try:
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 20000)
        band, basis = V._evidence_band(real)
        assert band == "none" and basis["band_label"]
        alignment, _l, msg, _r, _b = V._alignment_of("recommend", real)
        assert alignment == "unverified" and "不下判断" in msg
    finally:
        _cleanup_thin()

    # thin：5 条 → 不下强判断，但把看到的事实摆出来（不是一句「不知道」了事）
    _seed_thin(5)
    try:
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 20000)
        band, basis = V._evidence_band(real)
        assert band == "thin"
        assert basis["gate_passed"] is False, "偏薄 ≠ 可判断，红线不变"
        alignment, _l, msg, _r, _b = V._alignment_of("recommend", real)
        assert alignment == "unverified"
        assert "样本偏薄" in msg
        assert "最容易触及" in msg or "不等于" in msg, "偏薄时要给方向性事实，而不是空白"
    finally:
        _cleanup_thin()

    # full：12 条 / 5 所 → 允许判断
    _seed_thin(12)
    try:
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 20000)
        assert V._evidence_band(real)[0] == "full"
    finally:
        _cleanup_thin()


def test_refute_needs_more_evidence_than_support():
    """S8-B：「够不到任何院校」是全称否定，门槛必须高于「够得到某一所」。"""
    # 12 条 / 12 所：过一般门槛，但没过 refute 门槛 → 不许断言「够不到」
    _seed_distinct(12, rank_base=1000)
    try:
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 999999)
        assert real["reachable"] == 0
        band, basis = V._evidence_band(real)
        assert band == "full" and basis["refute_gate_passed"] is False
        alignment, _l, msg, _r, _b = V._alignment_of("recommend", real)
        assert alignment == "unverified", "样本不够厚时不能给出全称否定判断"
        assert "全称否定" in msg
    finally:
        _cleanup_thin()

    # 22 条 / 22 所：过 refute 门槛 → 才允许 refuted
    _seed_distinct(22, rank_base=1000)
    try:
        real = V.real_reachability(THIN_PROVINCE, THIN_SUBJECT, 999999)
        band, basis = V._evidence_band(real)
        assert band == "full" and basis["refute_gate_passed"] is True
        alignment, _l, _msg, _r, _b = V._alignment_of("recommend", real)
        assert alignment == "refuted"
    finally:
        _cleanup_thin()


def test_gate_profile_reports_real_distribution():
    """S8-B：门槛校准台账要能回答「10/5 合不合理」——把真实分布摆出来。"""
    prof = V.gate_profile()
    assert set(prof["bands"]) == {"full", "thin", "none"}
    assert set(prof["thresholds"]) == {"thin", "full", "refute"}
    assert prof["combos"] > 0
    assert sum(prof["bands"].values()) == prof["combos"]
    # 每条明细都带校线数/院校数/所在档，供人工核对阈值
    for d in prof["detail"]:
        assert d["lines"] > 0 and d["schools"] > 0
        assert d["band"] in ("full", "thin", "none")


def test_verify_api_exposes_alignment_basis():
    """接口把判断依据一并给前端，让「为什么是这个结论」可查。"""
    _seed_thin(2)
    try:
        r = c.post("/api/verify", json={"province": THIN_PROVINCE, "subject": THIN_SUBJECT,
                                        "user_rank": 20000, "major_name": "计算机科学与技术"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["alignment"] == "unverified"
        basis = j.get("alignment_basis") or {}
        assert basis.get("gate_passed") is False
        assert basis.get("total_lines") == 2

        r2 = c.post("/api/verify", json={"province": "河南", "subject": "物理类",
                                         "user_rank": 20000, "major_name": "计算机科学与技术"})
        assert r2.status_code == 200, r2.text
        j2 = r2.json()
        assert j2["alignment"] in ("supported", "refuted")
        assert (j2.get("alignment_basis") or {}).get("gate_passed") is True
    finally:
        _cleanup_thin()
