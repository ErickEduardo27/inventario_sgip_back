"""Estado en vivo de exportaciones en Redis: progreso, suscriptores, avisos y eventos (Pub/Sub).

La base de datos solo guarda las transiciones (en cola → procesando → listo / error). El progreso fino,
quién espera cada archivo y los avisos por usuario viven aquí para que consultar el estado nunca toque
PostgreSQL. Todo es tolerante a fallos: si Redis no responde, las funciones devuelven vacío y el API cae
a la base de datos (y el navegador a polling).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import UUID

from app.core.config import get_settings

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 7 * 24 * 3600
MINE_MAX_ITEMS = 40
HEARTBEAT_TTL_SECONDS = 120

_client = None
_client_failed_at = 0.0


def redis_url() -> str:
    s = get_settings()
    return (s.export_redis_url or "").strip() or (s.celery_broker_url or "").strip() or "redis://127.0.0.1:6379/0"


def client():
    """Cliente Redis síncrono (API y worker). ``None`` si no hay conexión (reintenta cada 30 s)."""
    global _client, _client_failed_at
    if _client is not None:
        return _client
    if time.monotonic() - _client_failed_at < 30:
        return None
    try:
        from redis import Redis

        # protocol=2 (RESP2): compatible con cualquier versión de Redis (RESP3 exige Redis 6+).
        c = Redis.from_url(
            redis_url(), decode_responses=True, socket_timeout=2, socket_connect_timeout=2, protocol=2
        )
        c.ping()
        _client = c
        return c
    except Exception:  # noqa: BLE001
        _client_failed_at = time.monotonic()
        logger.warning("Redis de exportaciones no disponible; se usa la base de datos", exc_info=True)
        return None


def _safe(fn, default=None):
    c = client()
    if c is None:
        return default
    try:
        return fn(c)
    except Exception:  # noqa: BLE001
        global _client
        _client = None
        logger.warning("Error de Redis en exportaciones", exc_info=True)
        return default


def _k_job(job_id: UUID | str) -> str:
    return f"exp:job:{job_id}"


def _k_subs(job_id: UUID | str) -> str:
    return f"exp:subs:{job_id}"


def _k_hb(job_id: UUID | str) -> str:
    return f"exp:hb:{job_id}"


def _k_mine(tenant_id: UUID | str, user_id: UUID | str) -> str:
    return f"exp:mine:{tenant_id}:{user_id}"


def _k_seen(tenant_id: UUID | str, user_id: UUID | str) -> str:
    return f"exp:seen:{tenant_id}:{user_id}"


def user_channel(tenant_id: UUID | str, user_id: UUID | str) -> str:
    return f"exp:ch:{tenant_id}:{user_id}"


# --- Estado del trabajo ---------------------------------------------------


def write_job(job_id: UUID | str, fields: dict[str, Any]) -> None:
    data = {k: ("" if v is None else str(v)) for k, v in fields.items()}

    def op(c):
        pipe = c.pipeline()
        # Un campo por comando: HSET con varios campos exige Redis 4+.
        for field, value in data.items():
            pipe.hset(_k_job(job_id), field, value)
        pipe.expire(_k_job(job_id), JOB_TTL_SECONDS)
        pipe.execute()

    _safe(op)


def read_job(job_id: UUID | str) -> dict[str, str] | None:
    data = _safe(lambda c: c.hgetall(_k_job(job_id)))
    return data or None


def read_jobs(job_ids: list[str]) -> dict[str, dict[str, str]]:
    if not job_ids:
        return {}

    def op(c):
        pipe = c.pipeline()
        for jid in job_ids:
            pipe.hgetall(_k_job(jid))
        return dict(zip(job_ids, pipe.execute()))

    return {k: v for k, v in (_safe(op, {}) or {}).items() if v}


def heartbeat(job_id: UUID | str) -> None:
    _safe(lambda c: c.set(_k_hb(job_id), "1", ex=HEARTBEAT_TTL_SECONDS))


def is_alive(job_id: UUID | str) -> bool | None:
    """True/False según el latido del worker; ``None`` si Redis no está disponible."""
    res = _safe(lambda c: bool(c.exists(_k_hb(job_id))), default=None)
    return res


# --- Suscriptores y avisos por usuario -------------------------------------


def add_subscriber(tenant_id: UUID | str, job_id: UUID | str, user_id: UUID | str) -> None:
    now_ms = int(time.time() * 1000)

    def op(c):
        pipe = c.pipeline()
        pipe.sadd(_k_subs(job_id), str(user_id))
        pipe.expire(_k_subs(job_id), JOB_TTL_SECONDS)
        mine = _k_mine(tenant_id, user_id)
        pipe.zadd(mine, {str(job_id): now_ms})
        pipe.zremrangebyrank(mine, 0, -(MINE_MAX_ITEMS + 1))
        pipe.expire(mine, JOB_TTL_SECONDS)
        pipe.srem(_k_seen(tenant_id, user_id), str(job_id))
        pipe.execute()

    _safe(op)


def subscribers(job_id: UUID | str) -> set[str]:
    return set(_safe(lambda c: c.smembers(_k_subs(job_id)), set()) or set())


def my_job_ids(tenant_id: UUID | str, user_id: UUID | str, limit: int = 20) -> list[str]:
    return list(_safe(lambda c: c.zrevrange(_k_mine(tenant_id, user_id), 0, limit - 1), []) or [])


def seen_ids(tenant_id: UUID | str, user_id: UUID | str) -> set[str]:
    return set(_safe(lambda c: c.smembers(_k_seen(tenant_id, user_id)), set()) or set())


def mark_seen(tenant_id: UUID | str, user_id: UUID | str, job_ids: list[str]) -> None:
    if not job_ids:
        return

    def op(c):
        pipe = c.pipeline()
        pipe.sadd(_k_seen(tenant_id, user_id), *job_ids)
        pipe.expire(_k_seen(tenant_id, user_id), JOB_TTL_SECONDS)
        pipe.execute()

    _safe(op)


def forget(tenant_id: UUID | str, user_id: UUID | str, job_id: str) -> None:
    def op(c):
        pipe = c.pipeline()
        pipe.zrem(_k_mine(tenant_id, user_id), job_id)
        pipe.srem(_k_subs(job_id), str(user_id))
        pipe.execute()

    _safe(op)


# --- Eventos ----------------------------------------------------------------


def publish(tenant_id: UUID | str, job_id: UUID | str, payload: dict[str, Any]) -> None:
    """Envía el estado a cada suscriptor por su canal (lo reenvía el endpoint SSE)."""
    subs = subscribers(job_id)
    if not subs:
        return
    message = json.dumps({"type": "job", "job": payload}, default=str)

    def op(c):
        pipe = c.pipeline()
        for uid in subs:
            pipe.publish(user_channel(tenant_id, uid), message)
        pipe.execute()

    _safe(op)
