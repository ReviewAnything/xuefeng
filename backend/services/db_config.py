"""数据库配置：多方言连接串构建、试连、落盘与切换初始化（管理端多数据库配置）。

设计要点
--------
1. **配置落盘而非只存内存**：写入 ``backend/data/db_config.json``（含口令，权限 600，
   已 gitignore），服务重启后自动装载，避免「配置了但重启就回退到 SQLite」。
2. **优先级明确**：环境变量 ``XUEFENG_DATABASE_URL`` / ``XUEFENG_DB_PATH`` > 管理端配置
   > 默认 SQLite。部署态不会被页面上的一次误操作覆盖。
3. **先试连再落盘**：连不上就拒绝保存，绝不把服务切到一个不可用的库上。
4. **切换即初始化**：保存后立刻建表 + 轻量迁移 + 幂等播种（这就是「配置成功即落盘数据」），
   并把当前管理员账号搬过去，避免切换后登录态失效把自己锁在门外。
5. **失败可回滚**：初始化阶段任何异常都切回原连接串并重建引擎，保证服务仍可用。
6. **口令不出网**：对外一律返回掩码，前端只回传「原样保留」的空口令或新口令。
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
CONFIG_PATH = os.path.join(DATA_DIR, "db_config.json")

MASK = "••••••"

# 方言元信息：驱动候选按「推荐 → 备选」排列，install 字段给运维可直接复制的命令。
DIALECTS = [
    {
        "key": "sqlite",
        "label": "SQLite（本地文件）",
        "default_port": 0,
        "fields": ["path"],
        "note": "零配置单文件，适合单机与演示；并发写入能力弱。",
        "drivers": [{"name": "sqlite3", "module": "sqlite3", "drivername": "",
                     "install": "Python 内置，无需安装"}],
    },
    {
        "key": "postgresql",
        "label": "PostgreSQL",
        "default_port": 5432,
        "fields": ["host", "port", "database", "username", "password"],
        "note": "推荐生产使用；事务与并发表现最好。",
        "drivers": [
            {"name": "psycopg3", "module": "psycopg", "drivername": "psycopg",
             "install": 'pip install "psycopg[binary]"'},
            {"name": "psycopg2", "module": "psycopg2", "drivername": "psycopg2",
             "install": "pip install psycopg2-binary"},
        ],
    },
    {
        "key": "mysql",
        "label": "MySQL",
        "default_port": 3306,
        "fields": ["host", "port", "database", "username", "password"],
        "note": "需 utf8mb4 字符集，建表由 SQLAlchemy 自动处理。",
        "drivers": [
            {"name": "pymysql", "module": "pymysql", "drivername": "pymysql",
             "install": "pip install pymysql"},
            {"name": "mysqlclient", "module": "MySQLdb", "drivername": "mysqldb",
             "install": "pip install mysqlclient"},
        ],
    },
    {
        "key": "mariadb",
        "label": "MariaDB",
        "default_port": 3306,
        "fields": ["host", "port", "database", "username", "password"],
        "note": "MySQL 同源分支；SQLAlchemy 有独立 mariadb 方言，驱动可复用 pymysql。",
        "drivers": [
            {"name": "pymysql", "module": "pymysql", "drivername": "pymysql",
             "install": "pip install pymysql"},
            {"name": "mariadb-connector", "module": "mariadb", "drivername": "mariadbconnector",
             "install": "pip install mariadb"},
        ],
    },
    {
        "key": "mssql",
        "label": "SQL Server",
        "default_port": 1433,
        "fields": ["host", "port", "database", "username", "password"],
        "note": "依赖 pyodbc 与系统 ODBC 驱动（默认 ODBC Driver 18，已附信任证书参数）。",
        "drivers": [
            {"name": "pyodbc", "module": "pyodbc", "drivername": "pyodbc",
             "install": "pip install pyodbc"},
            {"name": "pymssql", "module": "pymssql", "drivername": "pymssql",
             "install": "pip install pymssql"},
        ],
    },
]

# 裸连接串允许的前缀（高级模式直接填 URL 时用）
ALLOWED_SCHEMES = ("sqlite", "postgresql", "postgres", "mysql", "mariadb", "mssql")

VERSION_SQL = {
    "sqlite": "SELECT sqlite_version()",
    "postgresql": "SELECT version()",
    "mysql": "SELECT version()",
    "mariadb": "SELECT version()",
    "mssql": "SELECT @@version",
}

DEFAULT_SQLITE_PATH = os.path.join(DATA_DIR, "xuefeng.db")


def dialects() -> list[dict]:
    """给前端的选择项（含驱动是否已安装）。"""
    out = []
    for d in DIALECTS:
        item = dict(d)
        item["drivers"] = [
            {**drv, "installed": _module_installed(drv["module"])}
            for drv in d["drivers"]
        ]
        item["ready"] = any(x["installed"] for x in item["drivers"])
        out.append(item)
    return out


def _module_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _dialect_meta(key: str) -> dict:
    for d in DIALECTS:
        if d["key"] == key:
            return d
    raise ValueError(f"不支持的数据库类型：{key}")


def blank_config() -> dict:
    return {
        "dialect": "sqlite",
        "mode": "form",          # form：按字段拼装；url：直接填连接串
        "host": "",
        "port": None,
        "database": "",
        "username": "",
        "password": "",
        "path": DEFAULT_SQLITE_PATH,
        "url": "",
        "ssl": False,
    }


def normalize(cfg: dict | None) -> dict:
    """补全缺省字段并做类型收敛（不校验连通性）。"""
    base = blank_config()
    cfg = dict(cfg or {})
    out = {k: cfg.get(k, v) for k, v in base.items()}
    dialect = str(out.get("dialect") or "sqlite").strip().lower()
    _dialect_meta(dialect)                      # 非法方言直接抛错
    out["dialect"] = dialect
    out["mode"] = "url" if str(out.get("mode")) == "url" else "form"
    try:
        out["port"] = int(out["port"]) if out["port"] not in (None, "") else None
    except (TypeError, ValueError):
        out["port"] = None
    for key in ("host", "database", "username", "password", "path", "url"):
        out[key] = str(out[key] or "").strip()
    out["ssl"] = bool(out.get("ssl"))
    if dialect == "sqlite" and not out["path"]:
        out["path"] = DEFAULT_SQLITE_PATH
    if out["port"] is None and dialect != "sqlite":
        out["port"] = _dialect_meta(dialect)["default_port"]
    return out


def pick_driver(dialect: str) -> dict | None:
    """挑一个本机已安装的驱动；没有则返回 None（调用方应给出安装提示）。"""
    for drv in _dialect_meta(dialect)["drivers"]:
        if drv["drivername"] == "":        # sqlite：内置
            return drv
        if _module_installed(drv["module"]):
            return drv
    return None


def build_url(cfg: dict) -> str:
    """按方言拼 SQLAlchemy 连接串（显式带驱动名，口令做 URL 编码）。"""
    cfg = normalize(cfg)
    dialect = cfg["dialect"]
    if cfg["mode"] == "url":
        url = cfg["url"].strip()
        if not url:
            raise ValueError("高级模式下连接串不能为空")
        if not url.split("://", 1)[0].split("+", 1)[0].lower() in ALLOWED_SCHEMES:
            raise ValueError(f"连接串前缀不支持：{url.split('://', 1)[0]}")
        return url
    if dialect == "sqlite":
        path = cfg["path"] or DEFAULT_SQLITE_PATH
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return f"sqlite:///{path}"
    host = cfg["host"]
    if not host:
        raise ValueError("请填写数据库主机")
    if not cfg["database"]:
        raise ValueError("请填写数据库名")
    user = quote_plus(cfg["username"] or "")
    pwd = quote_plus(cfg["password"] or "")
    port = cfg["port"] or _dialect_meta(dialect)["default_port"]
    cred = f"{user}:{pwd}@" if user else (f":{pwd}@" if pwd else "")
    base = f"{host}:{port}" if port else host
    # 显式写驱动名：SQLAlchemy 各版本默认驱动并不一致（2.1 的 postgresql 默认已是 psycopg3）
    picked = pick_driver(dialect)
    scheme = f"{dialect}+{picked['drivername']}" if (picked and picked["drivername"]) else dialect
    url = f"{scheme}://{cred}{base}/{cfg['database']}"
    if dialect == "mysql":
        url += "?charset=utf8mb4"
    elif dialect == "mssql":
        url += "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    return url


def _scheme_of(url: str) -> str:
    return (url or "").split("://", 1)[0].split("+", 1)[0].lower()


def _mask_url(url: str) -> str:
    """把连接串里的口令替换成掩码，避免泄漏到日志/浏览器。"""
    if "://" not in (url or ""):
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    cred, tail = rest.split("@", 1)
    if ":" in cred:
        user = cred.split(":", 1)[0]
        cred = f"{user}:{MASK}"
    else:
        cred = MASK
    return f"{scheme}://{cred}@{tail}"


def public_config(cfg: dict | None) -> dict:
    """对外视图：口令只回 ``password_set`` 标记，连接串掩码。"""
    cfg = normalize(cfg)
    out = dict(cfg)
    out["password"] = MASK if cfg["password"] else ""
    out["password_set"] = bool(cfg["password"])
    out["port"] = cfg["port"] or _dialect_meta(cfg["dialect"])["default_port"]
    try:
        out["url_preview"] = _mask_url(build_url(cfg))
    except Exception as exc:  # 表单没填完时也允许回显
        out["url_preview"] = f"（待补全：{exc}）"
    return out


# ---------------------------------------------------------------- 读写落盘

def _ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load_raw() -> dict:
    """读取磁盘上的配置；不存在则返回空 dict。"""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def saved_config() -> dict:
    """落盘配置（含口令，仅服务端内部使用）。"""
    raw = load_raw()
    cfg = raw.get("config")
    if not isinstance(cfg, dict):
        return {}
    try:
        return normalize(cfg)
    except ValueError:
        return {}


def save_config(cfg: dict, applied: dict | None = None) -> dict:
    """写盘（0600），并把上次应用结果一并记录。"""
    _ensure_dir()
    raw = load_raw()
    raw["config"] = normalize(cfg)
    raw["updated_at"] = _now()
    if applied is not None:
        raw["last_applied"] = applied
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)     # 内含数据库口令
    except OSError:                      # Windows / 只读卷不致命
        pass
    return raw


def clear_config() -> None:
    """恢复默认 SQLite：删除落盘配置。"""
    try:
        os.remove(CONFIG_PATH)
    except FileNotFoundError:
        pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state() -> dict:
    """管理端「系统设置」首屏要的全部信息。"""
    from db.database import (DEFAULT_DB_PATH, active_url_source, database_url,
                             get_database_url_override)

    saved = saved_config()
    url = database_url()
    dialect = _dialect_of_url(url)
    env_url = os.environ.get("XUEFENG_DATABASE_URL")
    return {
        "ok": True,
        "config": public_config(saved or blank_config()),
        "saved": bool(saved),
        "source": active_url_source(),
        "env_url": _mask_url(env_url) if env_url else "",
        "env_locked": bool(env_url or os.environ.get("XUEFENG_DB_PATH")),
        "override": _mask_url(get_database_url_override()),
        "active": {
            "url": _mask_url(url),
            "dialect": dialect,
            "label": _dialect_label(dialect),
        },
        "default_path": DEFAULT_DB_PATH,
        "dialects": dialects(),
        "last_applied": load_raw().get("last_applied") or None,
    }


def _dialect_of_url(url: str) -> str:
    scheme = _scheme_of(url)
    if scheme.startswith("postgres"):
        return "postgresql"
    if scheme in ("sqlite", "mysql", "mariadb", "mssql"):
        return scheme
    return "unknown"


def _dialect_label(key: str) -> str:
    for d in DIALECTS:
        if d["key"] == key:
            return d["label"]
    return key


# ---------------------------------------------------------------- 连通性

def _connect_args(dialect: str, timeout: int) -> dict:
    if dialect == "sqlite":
        return {"check_same_thread": False, "timeout": max(1, timeout)}
    if dialect == "mysql":
        return {"connect_timeout": max(1, timeout)}
    if dialect == "mssql":
        return {"timeout": max(1, timeout)}
    return {"connect_timeout": max(1, timeout)}


def _driver_hint(dialect: str) -> str:
    meta = _dialect_meta(dialect)
    missing = [d for d in meta["drivers"] if not _module_installed(d["module"])]
    if len(missing) == len(meta["drivers"]):
        return "缺少数据库驱动：" + "；".join(d["install"] for d in missing)
    return ""


def test_connection(cfg: dict, timeout: int = 8) -> dict:
    """只试连、不落盘、不切换：返回版本与耗时，失败给出可执行的修复提示。"""
    started = time.perf_counter()
    try:
        url = build_url(cfg)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "hint": "", "url": ""}
    dialect = _dialect_of_url(url)
    norm = normalize(cfg)
    hint = _driver_hint(dialect) if dialect != "sqlite" else ""
    if hint:
        return {"ok": False, "error": "本机未安装该数据库驱动", "hint": hint,
                "url": _mask_url(url), "dialect": dialect}
    kwargs = {"future": True, "pool_pre_ping": True}
    if dialect == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": max(1, timeout)}
    else:
        kwargs["connect_args"] = _connect_args(dialect, timeout)
        kwargs["pool_timeout"] = max(1, timeout)
    engine = None
    try:
        engine = create_engine(url, **kwargs)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            version = ""
            try:
                version = str(conn.execute(text(VERSION_SQL.get(dialect, "SELECT 1"))).scalar() or "")
            except Exception:
                version = ""
        return {
            "ok": True,
            "dialect": dialect,
            "label": _dialect_label(dialect),
            "url": _mask_url(url),
            "server_version": version[:120],
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "hint": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "dialect": dialect,
            "url": _mask_url(url),
            "error": f"{type(exc).__name__}: {exc}"[:400],
            "hint": _hint_for(dialect, str(exc)),
        }
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass


def _hint_for(dialect: str, message: str) -> str:
    msg = (message or "").lower()
    if "authentication" in msg or "password" in msg or "access denied" in msg:
        return "账号或密码不对，或该账号没有从本机访问的权限"
    if "unknown database" in msg or "does not exist" in msg:
        return "数据库不存在，请先在服务端建库（CREATE DATABASE）"
    if "timed out" in msg or "timeout" in msg or "refused" in msg or "unreachable" in msg:
        return "连不上主机：检查地址/端口、防火墙与数据库是否放行远程连接"
    if "ssl" in msg:
        return "服务端要求 SSL 连接，请改用高级模式在连接串里补 sslmode 参数"
    if "driver" in msg or "module" in msg:
        return _driver_hint(dialect) or "驱动加载失败，请确认已安装对应数据库驱动"
    return "请检查主机、端口、库名与账号权限"


# ---------------------------------------------------------------- 应用（切换 + 初始化）

def _carry_admin_users() -> list[dict]:
    """切换前把现有管理员账号读出来，切换后原样搬进新库，避免把自己锁在门外。"""
    from db.database import session_scope
    from db.models import AdminUser

    try:
        with session_scope() as s:
            rows = s.query(AdminUser).all()
            return [{
                "username": r.username,
                "password_hash": r.password_hash,
                "salt": r.salt,
                "role": r.role,
                "must_change_password": bool(r.must_change_password),
                "password_changed_at": r.password_changed_at,
                "failed_attempts": r.failed_attempts or 0,
                "locked_until": r.locked_until,
                # created_at 参与令牌的密码版本戳（password_stamp）：不带上会让令牌失效
                **({"created_at": r.created_at} if r.created_at else {}),
                **({"last_login_at": r.last_login_at} if r.last_login_at else {}),
            } for r in rows]
    except Exception:
        return []


def _restore_admin_users(rows: list[dict]) -> int:
    """把账号搬进新库：新库没有就新增；若是播种出来的初始口令账号则覆盖为原凭据，
    这样登录态不会失效；已经是自定义口令的账号保持不动，避免覆盖生产环境账号。"""
    if not rows:
        return 0
    from db.database import session_scope
    from db.models import AdminUser
    from sqlalchemy import select

    moved = 0
    with session_scope() as s:
        for row in rows:
            exist = s.scalar(select(AdminUser).where(AdminUser.username == row["username"]))
            if exist is None:
                s.add(AdminUser(**row))
                moved += 1
            elif exist.must_change_password:
                for key, value in row.items():
                    setattr(exist, key, value)
                moved += 1
    return moved


def _table_stats() -> dict:
    from db.database import get_engine, session_scope
    from db.models import (AdmissionBaseline, SchoolLine, University)

    try:
        tables = len(inspect(get_engine()).get_table_names())
    except Exception:
        tables = 0
    try:
        with session_scope() as s:
            return {
                "tables": tables,
                "universities": int(s.scalar(_count(University)) or 0),
                "baselines": int(s.scalar(_count(AdmissionBaseline)) or 0),
                "school_lines": int(s.scalar(_count(SchoolLine)) or 0),
            }
    except Exception:
        return {"tables": tables, "universities": 0, "baselines": 0, "school_lines": 0}


def _count(model):
    from sqlalchemy import func, select
    return select(func.count()).select_from(model)


def apply_config(cfg: dict, seed: bool = True, username: str = "") -> dict:
    """试连 → 落盘 → 切换 → 建表迁移播种 → 记录结果。

    任一步失败都不改动生效连接（回滚到切换前），返回 ``ok=False`` 与原因。
    """
    from db.database import get_database_url_override, init_db, reset_engine, set_database_url

    norm = normalize(cfg)
    norm["password"] = _merge_password(norm, saved_config())   # 空口令＝沿用已保存口令
    probe = test_connection(norm)
    if not probe["ok"]:
        return {"ok": False, "stage": "connect", **probe}
    url = build_url(norm)

    previous_override = get_database_url_override()
    carried = _carry_admin_users()
    started = time.perf_counter()
    try:
        set_database_url(url)
        reset_engine()
        # 切换即初始化：建表 → 轻量迁移 → 幂等播种（数据真正落到新库）
        boot = init_db(seed=seed)
    except Exception as exc:
        # 回滚：切回原连接，保证服务仍可用
        set_database_url(previous_override)
        try:
            reset_engine()
        except Exception:
            pass
        return {"ok": False, "stage": "init",
                "error": f"{type(exc).__name__}: {exc}"[:400],
                "hint": "已回滚到切换前的数据库，服务未受影响",
                "url": _mask_url(url)}
    moved = _restore_admin_users(carried)
    stats = _table_stats()
    applied = {
        "ok": True,
        "at": _now(),
        "by": username or "",
        "dialect": probe.get("dialect", ""),
        "label": probe.get("label", ""),
        "url": _mask_url(url),
        "seed": bool(seed),
        "stats": stats,
        "admin_carried": moved,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "migration": (boot or {}).get("migration", {}),
    }
    save_config(norm, applied)
    # init_db 只在 seed=False 时回 seeded 标记，这里按「真的落了多少院校」判断是否播种成功
    return {"ok": True, "stage": "done", **applied,
            "seeded": bool(seed) and stats.get("universities", 0) > 0,
            "boot": {k: v for k, v in (boot or {}).items() if k != "migration"}}


def _merge_password(new_cfg: dict, saved: dict) -> str:
    """前端回传空口令表示「沿用已保存的口令」（同一方言+主机+库+账号时）。"""
    if new_cfg.get("password"):
        return new_cfg["password"]
    if not saved:
        return ""
    same = (saved.get("dialect") == new_cfg.get("dialect")
            and saved.get("host") == new_cfg.get("host")
            and saved.get("port") == new_cfg.get("port")
            and saved.get("database") == new_cfg.get("database")
            and saved.get("username") == new_cfg.get("username"))
    return saved.get("password", "") if same else ""


def reset_to_default(username: str = "") -> dict:
    """恢复默认 SQLite：清配置 + 切回默认连接 + 重新初始化。"""
    from db.database import init_db, reset_engine, set_database_url

    carried = _carry_admin_users()
    clear_config()
    set_database_url("")
    reset_engine()
    try:
        boot = init_db(seed=True)
    except Exception as exc:
        return {"ok": False, "stage": "init",
                "error": f"{type(exc).__name__}: {exc}"[:400]}
    _restore_admin_users(carried)
    return {"ok": True, "stage": "done", "url": _mask_url(f"sqlite:///{DEFAULT_SQLITE_PATH}"),
            "dialect": "sqlite", "label": _dialect_label("sqlite"),
            "stats": _table_stats(), "by": username or "", "at": _now(),
            "boot": {k: v for k, v in (boot or {}).items() if k != "migration"}}


def bootstrap() -> None:
    """进程启动时装载落盘配置（无配置则保持默认 SQLite）。"""
    cfg = saved_config()
    if not cfg:
        return
    from db.database import set_database_url

    try:
        set_database_url(build_url(cfg))
    except Exception:
        # 配置损坏时宁可回退默认库，也不要启动失败
        set_database_url("")
