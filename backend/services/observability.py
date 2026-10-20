"""可观测性（D3）：请求 ID、结构化访问日志、慢请求标记、运行时快照。

为什么不用第三方库
------------------
部署目标是「一个 uvicorn + SQLite」的小服务，日志只要能被 `docker logs` / Render 日志
采集即可；用 stdlib 打一行 JSON，比引 opentelemetry 更省事，也不影响冷启动。

约定
----
- 每个请求都有 `X-Request-ID`（客户端传了就沿用，便于串联前后端）；
- 访问日志一行一个 JSON：`time / level / rid / method / path / status / ms / ip`；
- 慢请求（默认 > 800ms）标 `level=warn` 并计入 `slow` 指标；
- `/admin/vendor/*` 静态资源不记访问日志（噪音大、无诊断价值）。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone

SLOW_MS = int(os.environ.get("XUEFENG_SLOW_MS", "800"))
LOG_ACCESS = os.environ.get("XUEFENG_ACCESS_LOG", "1").strip().lower() not in ("0", "false", "no")

_LOGGER = logging.getLogger("xuefeng.access")
_STARTED_AT = time.time()
_RECENT: deque[dict] = deque(maxlen=100)
_STATS = {"requests": 0, "errors": 0, "slow": 0, "total_ms": 0.0}


def _setup_logger() -> None:
    if _LOGGER.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False


def _emit(record: dict) -> None:
    _LOGGER.info(json.dumps(record, ensure_ascii=False))


def _record(method: str, path: str, status: int, ms: float, rid: str, ip: str) -> None:
    slow = ms >= SLOW_MS
    error = status >= 500
    _STATS["requests"] += 1
    _STATS["total_ms"] += ms
    if slow:
        _STATS["slow"] += 1
    if error:
        _STATS["errors"] += 1
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": "warn" if (slow or error) else "info",
        "rid": rid, "method": method, "path": path, "status": status,
        "ms": round(ms, 1), "ip": ip,
    }
    _RECENT.append(record)
    if LOG_ACCESS:
        _emit(record)


def install(app) -> None:
    """挂载访问日志中间件（在 app 定义之后、启动之前调用一次）。"""
    _setup_logger()

    @app.middleware("http")
    async def access_log(request, call_next):
        path = request.url.path
        if path.startswith("/admin/vendor/"):
            return await call_next(request)

        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        ip = (request.client.host if request.client else "") or ""
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            ms = (time.perf_counter() - started) * 1000
            _record(request.method, path, 500, ms, rid, ip)
            raise
        ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = rid
        _record(request.method, path, response.status_code, ms, rid, ip)
        return response


def snapshot(recent: int = 20) -> dict:
    """运行时快照：给 /api/health 用，也方便排障时一眼看清负载。"""
    total = _STATS["requests"]
    return {
        "uptime_seconds": int(time.time() - _STARTED_AT),
        "requests": total,
        "errors": _STATS["errors"],
        "slow": _STATS["slow"],
        "avg_ms": round(_STATS["total_ms"] / total, 1) if total else 0.0,
        "slow_threshold_ms": SLOW_MS,
        "recent": list(_RECENT)[-max(1, recent):],
    }
