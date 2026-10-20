"""数据库连接与会话管理。

默认 SQLite（零配置，文件位于 backend/data/xuefeng.db）；
生产可通过环境变量切换 PostgreSQL：
    XUEFENG_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/xuefeng
或单独指定 SQLite 路径：
    XUEFENG_DB_PATH=/var/lib/xuefeng/xuefeng.db
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "xuefeng.db")


# 管理端运行时配置（services/db_config.apply 写入），不落环境变量，避免污染进程环境
_override_url = ""


def database_url() -> str:
    """解析生效连接串，优先级：环境变量 > 管理端运行时配置 > SQLite 默认文件。

    环境变量（XUEFENG_DATABASE_URL / XUEFENG_DB_PATH）始终最高，保证部署态不会被
    页面上的一次误操作覆盖；管理端在「系统设置」里保存的配置写入
    ``backend/data/db_config.json``，由 services/db_config 在启动时/应用时装载进来。
    """
    url = os.environ.get("XUEFENG_DATABASE_URL")
    if url:
        return url
    if _override_url:
        return _override_url
    path = os.environ.get("XUEFENG_DB_PATH", DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return f"sqlite:///{path}"


def set_database_url(url: str) -> None:
    """设置运行时连接串；空串表示恢复默认 SQLite。仅影响本进程。"""
    global _override_url
    _override_url = (url or "").strip()


def get_database_url_override() -> str:
    return _override_url


def active_url_source() -> str:
    """当前连接串来自哪：env / admin-config / default。"""
    if os.environ.get("XUEFENG_DATABASE_URL"):
        return "env"
    if os.environ.get("XUEFENG_DB_PATH"):
        return "env-path"
    if _override_url:
        return "admin-config"
    return "default"


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        url = database_url()
        kwargs = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _record):  # pragma: no cover - 连接级钩子
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


@contextmanager
def session_scope():
    """事务上下文：正常提交，异常回滚。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(seed: bool = True) -> dict:
    """建表并在需要时播种，返回播种统计（幂等，可重复调用）。"""
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(get_engine())
    try:
        from .migrate import migrate

        migration = migrate()
    except Exception as exc:  # 迁移失败不应阻断启动（服务可走 JSON 兜底）
        migration = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "actions": []}
    if not seed:
        return {"seeded": False, "migration": migration}
    from . import seed as seed_mod

    seeded = seed_mod.ensure_seeded()
    seeded["migration"] = migration
    return seeded


def reset_engine() -> None:
    """测试用：释放引擎与缓存（切换数据库后调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
