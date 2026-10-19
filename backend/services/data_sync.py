"""数据源同步编排（L0 外部源 → L1 静态 JSON → L2 数据库）。

两类目标：
- **seed**：把仓库内静态 JSON 幂等播种进数据库（universities / admission / content）；
- **pipeline**：先跑 `scripts/` 下的 ingest / build 脚本重新生成 L1 JSON（可联网拉上游），
  再自动播种对应目标。

每次执行都会写 `sync_jobs` 记录（状态/行数/耗时/操作人），管理端「数据同步」页可见。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from db.database import session_scope
from db.models import SyncJob
from db import seed as seed_mod

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_TIMEOUT = 900  # 单个 ingest/build 脚本超时（秒）

# seed 类目标的展示名与说明
SEED_TARGETS: dict[str, dict] = {
    "universities": {"label": "院校总表", "kind": "seed",
                     "desc": "全国院校总表 + 985/211 清单 → universities / elite_universities"},
    "admission": {"label": "录取基线", "kind": "seed",
                  "desc": "31 省估算基线 + 官方省控线覆盖层 → admission_baselines"},
    "content": {"label": "专业与资源", "kind": "seed",
                "desc": "专业图谱与学习资源 → majors / resources"},
}

# pipeline 类目标：跑脚本重新生成 L1，再播种
PIPELINE_TARGETS: dict[str, dict] = {
    "ingest_baseline": {
        "label": "重新生成录取基线（gaokao-advisor）",
        "kind": "pipeline",
        "script": "scripts/ingest_gaokao_advisor.py",
        "refresh_args": ["--sync"],      # 勾选「拉取上游最新」时追加
        "outputs": ["data/admission_real_baseline.json"],
        "then_seed": ["admission"],
        "desc": "由 gaokao-advisor（MIT）参数重算 31 省基线，写出 admission_real_baseline.json 后自动播种",
    },
    "build_universities": {
        "label": "重新构建全国院校总表（教育部）",
        "kind": "pipeline",
        "script": "scripts/build_universities_national.py",
        "refresh_args": [],
        "outputs": ["data/universities_national.json"],
        "then_seed": ["universities"],
        "desc": "下载教育部《全国普通高等学校名单》官方 xls，重建 universities_national.json 后自动播种",
    },
}

ALL_TARGETS = {**SEED_TARGETS, **PIPELINE_TARGETS}


def targets_catalog() -> dict:
    """同步目标清单 + 每个目标最近一次执行记录。"""
    def last_job(kind: str, s) -> dict | None:
        from sqlalchemy import select
        row = s.scalar(select(SyncJob).where(SyncJob.kind == kind)
                       .order_by(SyncJob.id.desc()).limit(1))
        if row is None:
            return None
        return {"id": row.id, "status": row.status, "operator": row.operator,
                "message": row.message, "total": row.total,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "duration_ms": _duration_ms(row)}

    with session_scope() as s:
        out = {}
        for key, meta in ALL_TARGETS.items():
            out[key] = {**meta, "key": key, "last": last_job(key, s)}
        return {"ok": True, "targets": out,
                "seed_targets": list(SEED_TARGETS), "pipeline_targets": list(PIPELINE_TARGETS)}


def _duration_ms(job: SyncJob) -> int | None:
    if not job.finished_at or not job.created_at:
        return None
    return int((job.finished_at - job.created_at).total_seconds() * 1000)


def _run_script(script: str, extra_args: list[str]) -> tuple[bool, str]:
    """执行 scripts/ 下的脚本，返回 (是否成功, 输出摘要)。"""
    path = os.path.join(BACKEND_DIR, script)
    if not os.path.exists(path):
        return False, f"脚本不存在：{script}"
    cmd = [sys.executable, os.path.join("scripts", os.path.basename(script))] + list(extra_args)
    try:
        proc = subprocess.run(cmd, cwd=BACKEND_DIR, capture_output=True,
                              timeout=SCRIPT_TIMEOUT, text=True)
    except subprocess.TimeoutExpired:
        return False, f"脚本超时（>{SCRIPT_TIMEOUT}s）：{script}"
    except Exception as exc:  # pragma: no cover - 环境异常
        return False, f"脚本执行异常：{exc}"
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-3:]
        return False, "；".join(err + tail) or f"退出码 {proc.returncode}"
    return True, "；".join(tail) or "脚本执行完成"


def _seed(targets: list[str], force: bool) -> dict:
    stats = seed_mod.sync_all(targets, force=force)
    totals = {"total": 0, "inserted": 0, "updated": 0, "skipped": 0}
    for value in stats.values():
        if isinstance(value, dict):
            for k in totals:
                totals[k] += int(value.get(k, 0) or 0)
    return {"totals": totals, "raw": {k: v for k, v in stats.items() if isinstance(v, dict)}}


def run(targets: list[str], force: bool = False, refresh: bool = False,
        operator: str = "system") -> dict:
    """执行同步：每个目标一条 sync_jobs 记录。pipeline 目标会先跑脚本再播种。"""
    seed_keys = [t for t in targets if t in SEED_TARGETS]
    pipe_keys = [t for t in targets if t in PIPELINE_TARGETS]
    unknown = [t for t in targets if t not in ALL_TARGETS]
    if not seed_keys and not pipe_keys:
        return {"ok": False, "error": "未指定有效的同步目标", "unknown": unknown}

    results: dict[str, dict] = {}

    # 1) pipeline 优先：重新生成 L1 后自动播种（force=True，因为文件确实变了）
    for key in pipe_keys:
        meta = PIPELINE_TARGETS[key]
        results[key] = _run_one(key, meta, force=True, refresh=refresh, operator=operator)

    # 2) 纯播种目标
    for key in seed_keys:
        # 已被 pipeline 连带播种过的，不再重复
        if any(key in PIPELINE_TARGETS[p].get("then_seed", []) for p in pipe_keys
               if results.get(p, {}).get("ok")):
            results[key] = {"ok": True, "skipped_reason": f"已由 {[p for p in pipe_keys if key in PIPELINE_TARGETS[p].get('then_seed', [])][0]} 连带播种",
                            "totals": {"total": 0, "inserted": 0, "updated": 0, "skipped": 0}}
            continue
        results[key] = _run_one(key, SEED_TARGETS[key], force=force, refresh=False,
                                operator=operator)

    ok = all(v.get("ok") for v in results.values())
    return {"ok": ok, "results": results, "unknown": unknown,
            "message": "；".join(f"{ALL_TARGETS.get(k, {}).get('label', k)}: "
                                 f"{'成功' if v.get('ok') else '失败'}"
                                 for k, v in results.items())}


def _run_one(key: str, meta: dict, force: bool, refresh: bool, operator: str) -> dict:
    started = time.time()
    with session_scope() as s:
        job = SyncJob(kind=key, status="running", operator=operator)
        s.add(job)
        s.flush()
        job_id = job.id

    try:
        notes = []
        if meta["kind"] == "pipeline":
            args = list(meta.get("refresh_args", [])) if refresh else []
            ok, script_msg = _run_script(meta["script"], args)
            notes.append(f"脚本 {os.path.basename(meta['script'])}：{script_msg}")
            if not ok:
                _finish(job_id, "failed", {"total": 0, "inserted": 0, "updated": 0, "skipped": 0},
                        "；".join(notes))
                return {"ok": False, "error": script_msg, "job_id": job_id}
            seeded = _seed(meta.get("then_seed", []), force=True)
        else:
            seeded = _seed([key], force=force)
        totals = seeded["totals"]
        _invalidate_cache()
        notes.append(f"新增 {totals['inserted']} / 更新 {totals['updated']} / 跳过 {totals['skipped']}")
        _finish(job_id, "success", totals, "；".join(notes))
        return {"ok": True, "job_id": job_id, "totals": totals, "message": "；".join(notes),
                "duration_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        _finish(job_id, "failed", {"total": 0, "inserted": 0, "updated": 0, "skipped": 0},
                f"异常：{exc}")
        return {"ok": False, "error": str(exc), "job_id": job_id}


def _finish(job_id: int, status: str, totals: dict, message: str) -> None:
    with session_scope() as s:
        job = s.get(SyncJob, job_id)
        if job is None:
            return
        job.status = status
        job.total = int(totals.get("total", 0))
        job.inserted = int(totals.get("inserted", 0))
        job.updated = int(totals.get("updated", 0))
        job.skipped = int(totals.get("skipped", 0))
        job.message = (message or "")[:2000]
        job.finished_at = datetime.now(timezone.utc)


def _invalidate_cache() -> None:
    try:
        from services import admission as A
        A.invalidate_cache()
    except Exception:  # pragma: no cover
        pass
