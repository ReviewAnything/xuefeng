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
    """录取门槛基线：每 (省, 科类, 批次) 一行，官方值覆盖估算值。"""

    __tablename__ = "admission_baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(String(32), index=True)
    subject: Mapped[str] = mapped_column(String(16), index=True)
    tier: Mapped[str] = mapped_column(String(16))
    min_score: Mapped[int] = mapped_column(Integer, default=0)
    min_rank: Mapped[int] = mapped_column(Integer, default=0)
    data_source: Mapped[str] = mapped_column(String(16), default="estimated")   # official / estimated
    line: Mapped[str] = mapped_column(String(64), default="")                   # 官方线名称
    school: Mapped[str] = mapped_column(String(128), default="")                # 入门院校（学校层级）
    year: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str] = mapped_column(String(512), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("province", "subject", "tier", name="uq_baseline_province_subject_tier"),
        Index("ix_baseline_province_subject", "province", "subject"),
    )


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
    """管理端账号（PBKDF2 加盐哈希）。"""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    salt: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="admin")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Setting(Base):
    """键值配置（数据签名、鉴权密钥、内容元信息等）。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
