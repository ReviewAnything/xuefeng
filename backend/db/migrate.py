"""轻量 schema 迁移（不引入 Alembic，保持零配置）。

历史库的 admission_baselines 唯一键为 (province, subject, tier)，
无法并存多年数据；本模块把该表按新结构重建，并把年份回填到当前生效年份，
已发布的历史数据不会丢失。

迁移是幂等的：结构已是新版本时直接跳过。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import inspect, text

from .database import Base, get_engine, session_scope

# 新结构的列顺序（用于 INSERT ... SELECT，避免依赖物理顺序）
BASELINE_COLUMNS = [
    "id", "year", "source_year", "province", "subject", "tier", "min_score", "min_rank",
    "data_source", "line", "school", "carried", "source_url", "updated_at",
]


def _default_year() -> int:
    return datetime.now(timezone.utc).year


def _table_exists(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _baseline_has_year_key(insp) -> bool:
    for con in insp.get_unique_constraints("admission_baselines") or []:
        cols = set(con.get("column_names") or [])
        if cols and "year" in cols:
            return True
    return False


def _column_names(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def migrate() -> dict:
    """执行必要迁移，返回动作说明（供启动日志/管理端展示）。"""
    engine = get_engine()
    insp = inspect(engine)
    actions: list[str] = []

    if _table_exists(insp, "admission_baselines") and not _baseline_has_year_key(insp):
        # 历史库把「版本年份」和「出处年份」混在同一个 year 列里：
        # 统一取最大年份作为版本年份，原 year 退化为 source_year（官方线常滞后一年）。
        with engine.begin() as conn:
            max_year = conn.execute(text("SELECT MAX(year) FROM admission_baselines")).scalar()
        fallback_year = int(max_year) if max_year else _default_year()
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE admission_baselines RENAME TO admission_baselines_legacy"))
            # 旧索引会跟随表改名而保留，必须先清理，否则新结构建同名索引会冲突
            if engine.dialect.name == "sqlite":
                names = [r[0] for r in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='admission_baselines_legacy' AND sql IS NOT NULL")).all()]
                for name in names:
                    conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        # 用新结构建表（create_all 只建缺失的表）
        from . import models  # noqa: F401

        Base.metadata.create_all(engine)
        legacy_cols = _column_names(inspect(engine), "admission_baselines_legacy")

        def expr(name: str, fallback: str) -> str:
            return f"COALESCE({name}, {fallback})" if name in legacy_cols else fallback

        cols = ", ".join(BASELINE_COLUMNS)
        # year 统一为版本年份；原 year 退化为 source_year
        year_expr = str(fallback_year)
        source_expr = (f"COALESCE(NULLIF(source_year, 0), COALESCE(NULLIF(year, 0), {fallback_year}))"
                       if "source_year" in legacy_cols
                       else (f"COALESCE(NULLIF(year, 0), {fallback_year})"
                             if "year" in legacy_cols else str(fallback_year)))
        select_cols = ", ".join([
            "id", year_expr, source_expr,
            expr("province", "''"),
            expr("subject", "''"),
            expr("tier", "''"),
            expr("min_score", "0"),
            expr("min_rank", "0"),
            expr("data_source", "'estimated'"),
            expr("line", "''"),
            expr("school", "''"),
            "0",
            expr("source_url", "''"),
            expr("updated_at", "CURRENT_TIMESTAMP"),
        ])
        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO admission_baselines ({cols}) SELECT {select_cols} "
                "FROM admission_baselines_legacy"))
            conn.execute(text("DROP TABLE admission_baselines_legacy"))
            # 让播种重新执行一遍，补齐 carried / source_year 等新字段语义
            conn.execute(text("DELETE FROM settings WHERE key = 'seed_sig:admission'"))
        actions.append(f"admission_baselines 已重建为按年份共存结构（版本年份 {fallback_year}，"
                       "原年份保留为 source_year）")

    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    insp = inspect(engine)

    if _table_exists(insp, "admission_baselines"):
        cols = _column_names(insp, "admission_baselines")
        for col, ddl, label in (
            ("carried", "ALTER TABLE admission_baselines ADD COLUMN carried BOOLEAN DEFAULT 0", "carried"),
            ("source_year", f"ALTER TABLE admission_baselines ADD COLUMN source_year INTEGER DEFAULT {_default_year()}", "source_year"),
            ("year", f"ALTER TABLE admission_baselines ADD COLUMN year INTEGER DEFAULT {_default_year()}", "year"),
        ):
            if col not in cols:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                actions.append(f"admission_baselines 增加 {label} 列")

    return {"ok": True, "actions": actions, "migrated": bool(actions)}
