"""ORM 模型：院校、录取基线、精英院校、内容、运营数据。"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class University(Base):
    """全国普通高等学校（教育部官方名单，2868 所）。"""

    __tablename__ = "universities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    province: Mapped[str] = mapped_column(String(32), index=True, default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(16), index=True, default="")       # 本科 / 专科
    nature: Mapped[str] = mapped_column(String(32), default="")                  # 公办/民办/中外合作
    supervisor: Mapped[str] = mapped_column(String(128), default="")              # 主管部门
    code: Mapped[str] = mapped_column(String(32), default="")                     # 标识码
    category: Mapped[str] = mapped_column(String(32), index=True, default="")     # 门类（部分院校）
    is_985: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_211: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_dfc: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    website: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(64), default="moe")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (Index("ix_uni_province_level", "province", "level"),)


class SchoolLine(Base):
    """院校投档线（逐校真实数据，D1 导入）。

    与 ``AdmissionBaseline`` 的区别：基线是「省×科类×批次」的门槛，
    本表是「省×科类×院校（×专业组）」的逐校最低分/最低位次。
    ``university`` 存匹配到教育部 2868 所名单后的规范校名，``university_input``
    保留原始写法，便于回溯导入质量。
    """

    __tablename__ = "school_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, index=True, default=0)
    province: Mapped[str] = mapped_column(String(32), index=True, default="")
    subject: Mapped[str] = mapped_column(String(16), index=True, default="")
    batch: Mapped[str] = mapped_column(String(32), default="")
    university: Mapped[str] = mapped_column(String(128), index=True, default="")
    university_input: Mapped[str] = mapped_column(String(128), default="")
    group_code: Mapped[str] = mapped_column(String(32), default="")     # 院校专业组/专业代码
    min_score: Mapped[int] = mapped_column(Integer, default=0)
    min_rank: Mapped[int] = mapped_column(Integer, default=0)
    data_source: Mapped[str] = mapped_column(String(16), default="official")
    match_method: Mapped[str] = mapped_column(String(16), default="exact")  # exact/normalized/contains/fuzzy
    source_url: Mapped[str] = mapped_column(String(512), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("year", "province", "subject", "university", "group_code",
                         name="uq_school_line_key"),
        Index("ix_school_line_scope", "year", "province", "subject", "min_rank"),
    )


class EliteUniversity(Base):
    """985/211 权威清单（112 所，含军校与拆分校区）。"""

    __tablename__ = "elite_universities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    short: Mapped[str] = mapped_column(String(32), default="")
    province: Mapped[str] = mapped_column(String(32), index=True, default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    supervisor: Mapped[str] = mapped_column(String(128), default="")
    is_985: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_211: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_dfc: Mapped[bool] = mapped_column(Boolean, default=False)


class AdmissionBaseline(Base):
    """录取门槛基线：每 (年份, 省, 科类, 批次) 一行，官方值覆盖估算值。

    年份进入主键约束后，多年数据可并存（2024/2025/2026…），
    对外服务只读取「当前生效年份」（settings.data_active_year）。
    """

    __tablename__ = "admission_baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, default=0, index=True)          # 所属数据版本年份
    source_year: Mapped[int] = mapped_column(Integer, default=0)               # 数值实际出处年份（官方线常滞后一年）
    province: Mapped[str] = mapped_column(String(32), index=True)
    subject: Mapped[str] = mapped_column(String(16), index=True)
    tier: Mapped[str] = mapped_column(String(16))
    min_score: Mapped[int] = mapped_column(Integer, default=0)
    min_rank: Mapped[int] = mapped_column(Integer, default=0)
    data_source: Mapped[str] = mapped_column(String(16), default="estimated")   # official / estimated
    line: Mapped[str] = mapped_column(String(64), default="")                   # 官方线名称
    school: Mapped[str] = mapped_column(String(128), default="")                # 入门院校（学校层级）
    carried: Mapped[bool] = mapped_column(Boolean, default=False)               # 沿用上一年（待官方更新）
    source_url: Mapped[str] = mapped_column(String(512), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("year", "province", "subject", "tier", name="uq_baseline_year_province_subject_tier"),
        Index("ix_baseline_year_province_subject", "year", "province", "subject"),
    )


class DataVersion(Base):
    """数据版本：一个 (数据集, 年份) 一条，支持草稿→校验→发布→归档的完整生命周期。"""

    __tablename__ = "data_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(32), index=True)     # admission / universities / content
    year: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/validated/published/archived
    revision: Mapped[int] = mapped_column(Integer, default=1)         # 每次补丁 +1
    parent_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    official_rows: Mapped[int] = mapped_column(Integer, default=0)
    carried_rows: Mapped[int] = mapped_column(Integer, default=0)
    coverage: Mapped[str] = mapped_column(Text, default="[]")        # JSON：已覆盖省份
    checksum: Mapped[str] = mapped_column(String(64), default="")    # 内容指纹，用于判断是否有改动
    check_result: Mapped[str] = mapped_column(Text, default="{}")    # JSON：最近一次校验结果
    note: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("dataset", "year", name="uq_version_dataset_year"),)


class DataChange(Base):
    """数据变更审计：任何写入/发布/回滚都留痕，支持按条回滚。"""

    __tablename__ = "data_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(32), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(16), index=True)   # clone/patch/create/publish/rollback/import
    entity: Mapped[str] = mapped_column(String(128), default="")  # 基线主键描述："河南/物理类/一本"
    field: Mapped[str] = mapped_column(String(32), default="")    # min_score/min_rank/data_source/…
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Major(Base):
    """专业图谱（观点 + 偏见校正 + 核验入口）。"""

    __tablename__ = "majors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cat: Mapped[str] = mapped_column(String(32), index=True, default="")
    view: Mapped[str] = mapped_column(String(16), default="recommend")  # recommend/caution/avoid
    reason: Mapped[str] = mapped_column(Text, default="")
    bias: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")               # JSON 数组
    verify: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Resource(Base):
    """开源资源中心条目。"""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    cat: Mapped[str] = mapped_column(String(16), index=True, default="")
    lic: Mapped[str] = mapped_column(String(32), default="")
    meta: Mapped[str] = mapped_column(String(64), default="")
    desc: Mapped[str] = mapped_column(Text, default="")
    links: Mapped[str] = mapped_column(Text, default="[]")              # JSON 数组
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class QueryEvent(Base):
    """匿名查询事件（仅记录省份/科类/位次区间，用于看板统计，不含身份信息）。"""

    __tablename__ = "query_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)            # verify / search
    province: Mapped[str] = mapped_column(String(32), index=True, default="")
    subject: Mapped[str] = mapped_column(String(16), default="")
    user_rank: Mapped[int] = mapped_column(Integer, default=0)
    major_name: Mapped[str] = mapped_column(String(64), default="")
    alignment: Mapped[str] = mapped_column(String(16), default="")
    best_tier: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class SyncJob(Base):
    """数据同步任务记录（管理端可见）。"""

    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")   # running/success/failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminUser(Base):
    """管理端账号（PBKDF2 加盐哈希 + 登录失败锁定 + 密码变更时间）。"""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    salt: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="admin")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)             # 连续失败次数
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginAttempt(Base):
    """登录审计：成功/失败都留痕，用于限流判定与安全回溯（不含密码）。"""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True, default="")
    ip: Mapped[str] = mapped_column(String(64), index=True, default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reason: Mapped[str] = mapped_column(String(32), default="")   # bad_credentials/locked/ok/password_changed
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Setting(Base):
    """键值配置（数据签名、鉴权密钥、内容元信息等）。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
