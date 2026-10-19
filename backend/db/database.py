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


def database_url() -> str:
    url = os.environ.get("XUEFENG_DATABASE_URL")
    if url:
        return url
    path = os.environ.get("XUEFENG_DB_PATH", DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return f"sqlite:///{path}"


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
