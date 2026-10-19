"""数据落库层：SQLAlchemy + SQLite（可切换 PostgreSQL）。

对外只暴露少量入口，避免调用方感知引擎细节：
  - init_db()        建表 + 幂等播种
  - session_scope()  事务上下文
  - repository       业务查询（带缓存）
"""
from .database import Base, get_engine, init_db, session_scope  # noqa: F401

__all__ = ["Base", "get_engine", "init_db", "session_scope"]
