"""Cache materializado del resumen por local del dashboard."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.modules.inventory import models as m
from app.modules.tenants import models as _tenant_models  # noqa: F401 — FK tenants en metadata

logger = logging.getLogger(__name__)

DASHBOARD_STATS_IMPORT_MODULES = frozenset(
    {
        "establishments",
        "environments",
        "margesi",
        "margesi_moment",
        "hoja_captura",
        "cards",
    }
)

# Margesi e inventario se agregan en subconsultas separadas.
# Un JOIN único (margesi × ambientes × hojas × itemcards) genera producto cartesiano
# y puede tardar >20 min en un local grande.
_ESTABLISHMENT_STATS_SQL = """
    SELECT
        e.id AS establishment_id,
        e.code AS establishment_code,
        e.description AS establishment_description,
        COALESCE(ms.margesi_total, 0) AS margesi_total,
        COALESCE(ms.margesi_conciliado, 0) AS margesi_conciliado,
        COALESCE(ms.margesi_faltantes, 0) AS margesi_faltantes,
        COALESCE(ms.margesi_no_inventariable, 0) AS margesi_no_inventariable,
        COALESCE(inv.inventario_total, 0) AS inventario_total,
        COALESCE(inv.inventario_conciliado, 0) AS inventario_conciliado,
        COALESCE(inv.inventario_sobrante, 0) AS inventario_sobrante,
        COALESCE(inv.inventario_no_conciliable, 0) AS inventario_no_conciliable
    FROM establishments e
    LEFT JOIN (
        SELECT
            e2.id AS establishment_id,
            COUNT(marg.id)::int AS margesi_total,
            COUNT(marg.id) FILTER (WHERE marg.inv_sit = 'C')::int AS margesi_conciliado,
            COUNT(marg.id) FILTER (
                WHERE marg.inv_sit IS NULL
                   OR TRIM(COALESCE(marg.inv_sit, '')) = ''
                   OR marg.inv_sit IN ('-', '—', '–')
            )::int AS margesi_faltantes,
            COUNT(marg.id) FILTER (WHERE marg.inv_sit = 'N')::int AS margesi_no_inventariable
        FROM establishments e2
        INNER JOIN margesi marg
            ON marg.tenant_id = e2.tenant_id AND marg.amb_cod = e2.code
        WHERE e2.tenant_id = CAST(:tenant_id AS uuid)
          {establishment_filter_e2}
        GROUP BY e2.id
    ) ms ON ms.establishment_id = e.id
    LEFT JOIN (
        SELECT
            env.establishment_id,
            COUNT(ic.id)::int AS inventario_total,
            COUNT(ic.id) FILTER (WHERE ic.inv_sit = 'C')::int AS inventario_conciliado,
            COUNT(ic.id) FILTER (WHERE ic.inv_sit = 'S')::int AS inventario_sobrante,
            COUNT(ic.id) FILTER (WHERE ic.inv_sit = 'N')::int AS inventario_no_conciliable
        FROM enviroments env
        INNER JOIN cards c
            ON c.tenant_id = env.tenant_id AND c.id_ambiente = env.id
        INNER JOIN itemcards ic
            ON ic.tenant_id = c.tenant_id AND ic.id_card = c.id
        WHERE env.tenant_id = CAST(:tenant_id AS uuid)
          {establishment_filter_env}
        GROUP BY env.establishment_id
    ) inv ON inv.establishment_id = e.id
    WHERE e.tenant_id = CAST(:tenant_id AS uuid)
      {establishment_filter_e}
    ORDER BY e.code ASC
"""

_QUEUE_TTL_SECONDS = 90
_RUN_TTL_SECONDS = 1800
_redis_client = None


def _stats_redis():
    """Cliente Redis del broker Celery (None si Redis no está disponible)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        from redis import Redis

        from app.core.config import get_settings

        url = (get_settings().celery_broker_url or "").strip() or "redis://127.0.0.1:6379/0"
        _redis_client = Redis.from_url(url, decode_responses=True)
        return _redis_client
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis no disponible para debounce dashboard stats: %s", exc)
        return None


def _try_acquire(key: str, ttl: int) -> bool:
    client = _stats_redis()
    if client is None:
        return True
    try:
        return bool(client.set(key, "1", nx=True, ex=ttl))
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo tomar lock %s: %s", key, exc)
        return True


def release_dashboard_stats_lock(key: str) -> None:
    client = _stats_redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo liberar lock %s: %s", key, exc)


def dashboard_stats_queue_key(tenant_id: UUID, establishment_id: int | None = None) -> str:
    if establishment_id is None:
        return f"dash-est-stats:q-tenant:{tenant_id}"
    return f"dash-est-stats:q:{tenant_id}:{int(establishment_id)}"


def dashboard_stats_run_key(tenant_id: UUID, establishment_id: int | None = None) -> str:
    if establishment_id is None:
        return f"dash-est-stats:run-tenant:{tenant_id}"
    return f"dash-est-stats:run:{tenant_id}:{int(establishment_id)}"


def try_begin_dashboard_stats_run(tenant_id: UUID, establishment_id: int | None = None) -> bool:
    """Evita que dos workers recalculen el mismo local a la vez."""
    qkey = dashboard_stats_queue_key(tenant_id, establishment_id)
    release_dashboard_stats_lock(qkey)
    return _try_acquire(dashboard_stats_run_key(tenant_id, establishment_id), _RUN_TTL_SECONDS)


def end_dashboard_stats_run(tenant_id: UUID, establishment_id: int | None = None) -> None:
    release_dashboard_stats_lock(dashboard_stats_run_key(tenant_id, establishment_id))


def _row_to_cache_dict(row: Any, refreshed_at: datetime) -> dict[str, Any]:
    return {
        "establishment_id": int(row["establishment_id"]),
        "establishment_code": str(row["establishment_code"] or ""),
        "establishment_description": row["establishment_description"],
        "margesi_total": int(row["margesi_total"] or 0),
        "margesi_conciliado": int(row["margesi_conciliado"] or 0),
        "margesi_faltantes": int(row["margesi_faltantes"] or 0),
        "margesi_no_inventariable": int(row["margesi_no_inventariable"] or 0),
        "inventario_total": int(row["inventario_total"] or 0),
        "inventario_conciliado": int(row["inventario_conciliado"] or 0),
        "inventario_sobrante": int(row["inventario_sobrante"] or 0),
        "inventario_no_conciliable": int(row["inventario_no_conciliable"] or 0),
        "refreshed_at": refreshed_at,
    }


def _fetch_stats_rows(
    db: Session,
    tenant_id: UUID,
    *,
    establishment_id: int | None = None,
) -> list[dict[str, Any]]:
    refreshed_at = datetime.now(timezone.utc)
    if establishment_id is not None:
        bind: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "establishment_id": establishment_id,
        }
        sql = _ESTABLISHMENT_STATS_SQL.format(
            establishment_filter_e="AND e.id = :establishment_id",
            establishment_filter_e2="AND e2.id = :establishment_id",
            establishment_filter_env="AND env.establishment_id = :establishment_id",
        )
    else:
        bind = {"tenant_id": str(tenant_id)}
        sql = _ESTABLISHMENT_STATS_SQL.format(
            establishment_filter_e="",
            establishment_filter_e2="",
            establishment_filter_env="",
        )
    rows = db.execute(text(sql), bind).mappings().all()
    return [_row_to_cache_dict(row, refreshed_at) for row in rows]


def _public_stats_dict(row: Any) -> dict[str, Any]:
    return {
        "establishment_id": int(row.establishment_id),
        "establishment_code": row.establishment_code,
        "establishment_description": row.establishment_description,
        "margesi_total": int(row.margesi_total or 0),
        "margesi_conciliado": int(row.margesi_conciliado or 0),
        "margesi_faltantes": int(row.margesi_faltantes or 0),
        "margesi_no_inventariable": int(row.margesi_no_inventariable or 0),
        "inventario_total": int(row.inventario_total or 0),
        "inventario_conciliado": int(row.inventario_conciliado or 0),
        "inventario_sobrante": int(row.inventario_sobrante or 0),
        "inventario_no_conciliable": int(row.inventario_no_conciliable or 0),
    }


def get_establishment_stats_live(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
) -> dict[str, Any]:
    """Totales Margesi/inventario de un local (consulta en vivo, sin cache)."""
    rows = _fetch_stats_rows(db, tenant_id, establishment_id=establishment_id)
    if not rows:
        raise ValueError("Local no encontrado")
    return {k: v for k, v in rows[0].items() if k != "refreshed_at"}


def get_establishment_stats(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
    *,
    live: bool = False,
) -> dict[str, Any]:
    """Lee cache materializado; si no hay fila, calcula en vivo."""
    if not live:
        cached = db.scalar(
            select(m.InvDashboardEstablishmentStat).where(
                m.InvDashboardEstablishmentStat.tenant_id == tenant_id,
                m.InvDashboardEstablishmentStat.establishment_id == establishment_id,
            ),
        )
        if cached is not None:
            return _public_stats_dict(cached)
    return get_establishment_stats_live(db, tenant_id, establishment_id)


def _upsert_stats_rows(db: Session, tenant_id: UUID, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    for data in rows:
        est_id = data["establishment_id"]
        existing = db.scalar(
            select(m.InvDashboardEstablishmentStat).where(
                m.InvDashboardEstablishmentStat.tenant_id == tenant_id,
                m.InvDashboardEstablishmentStat.establishment_id == est_id,
            ),
        )
        if existing is None:
            db.add(m.InvDashboardEstablishmentStat(tenant_id=tenant_id, **data))
        else:
            for key, value in data.items():
                setattr(existing, key, value)
            db.add(existing)
    db.commit()
    return len(rows)


def rebuild_dashboard_establishment_stats_for_establishment(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
) -> dict[str, int | str]:
    rows = _fetch_stats_rows(db, tenant_id, establishment_id=establishment_id)
    count = _upsert_stats_rows(db, tenant_id, rows)
    return {
        "tenant_id": str(tenant_id),
        "establishment_id": establishment_id,
        "row_count": count,
    }


def rebuild_dashboard_establishment_stats_tenant(db: Session, tenant_id: UUID) -> dict[str, int | str]:
    refreshed_at = datetime.now(timezone.utc)
    rows = _fetch_stats_rows(db, tenant_id)
    db.execute(
        delete(m.InvDashboardEstablishmentStat).where(
            m.InvDashboardEstablishmentStat.tenant_id == tenant_id,
        ),
    )
    for data in rows:
        db.add(m.InvDashboardEstablishmentStat(tenant_id=tenant_id, **data))
    db.commit()
    return {
        "tenant_id": str(tenant_id),
        "row_count": len(rows),
        "refreshed_at": refreshed_at.isoformat(),
    }


def establishment_ids_for_card(db: Session, tenant_id: UUID, card_id: int) -> list[int]:
    row = db.execute(
        text(
            """
            SELECT env.establishment_id
            FROM cards c
            JOIN enviroments env
              ON env.id = c.id_ambiente AND env.tenant_id = c.tenant_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.id = :card_id
              AND env.establishment_id IS NOT NULL
            """
        ),
        {"tenant_id": str(tenant_id), "card_id": card_id},
    ).first()
    if not row or row[0] is None:
        return []
    return [int(row[0])]


def establishment_ids_for_item_card(db: Session, tenant_id: UUID, item: m.InvItemCard) -> list[int]:
    return establishment_ids_for_card(db, tenant_id, int(item.id_card))


def establishment_ids_for_margesi(db: Session, tenant_id: UUID, row: m.InvMargesiItem) -> list[int]:
    amb_cod = (row.amb_cod or "").strip()
    if not amb_cod:
        return []
    est_id = db.scalar(
        select(m.InvEstablishment.id).where(
            m.InvEstablishment.tenant_id == tenant_id,
            m.InvEstablishment.code == amb_cod,
        ),
    )
    return [int(est_id)] if est_id is not None else []


def establishment_ids_for_conciliation_pair(
    db: Session,
    tenant_id: UUID,
    marg: m.InvMargesiItem,
    bien: m.InvItemCard,
) -> list[int]:
    ids = set(establishment_ids_for_margesi(db, tenant_id, marg))
    ids.update(establishment_ids_for_item_card(db, tenant_id, bien))
    return sorted(ids)


def schedule_dashboard_establishment_stats_deltas(
    tenant_id: UUID,
    deltas_by_establishment: dict[int, dict[str, int]],
    *,
    countdown: int = 1,
) -> None:
    """Encola deltas ya sumados (ideal tras imports masivos)."""
    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        get_dashboard_stats_batch,
    )

    if not deltas_by_establishment or not any(any(d.values()) for d in deltas_by_establishment.values()):
        return

    batch = get_dashboard_stats_batch()
    if batch is not None:
        batch.merge_deltas(deltas_by_establishment)
        return

    payload = {str(est_id): dict(deltas) for est_id, deltas in deltas_by_establishment.items()}
    try:
        from app.tasks.dashboard_establishment_stats import (
            apply_dashboard_establishment_stats_delta_task,
        )

        apply_dashboard_establishment_stats_delta_task.apply_async(
            kwargs={"tenant_id": str(tenant_id), "deltas_payload": payload},
            countdown=countdown,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo encolar deltas dashboard stats: %s", exc)


def flush_dashboard_stats_batch(tenant_id: UUID, collector: Any) -> None:
    """Envía a Celery los deltas acumulados en un import masivo."""
    if collector is None or collector.is_empty():
        return
    schedule_dashboard_establishment_stats_deltas(tenant_id, collector.merged_deltas(), countdown=0)


def schedule_dashboard_establishment_stats_incremental(
    tenant_id: UUID,
    changes: list[Any],
    *,
    countdown: int = 1,
) -> None:
    """Encola deltas incrementales (UPDATE +=) en Celery; no recalcula COUNT del local."""
    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        EstablishmentStatsChange,
        get_dashboard_stats_batch,
        merge_establishment_changes,
    )

    if not changes:
        return

    parsed = [
        c if isinstance(c, EstablishmentStatsChange) else EstablishmentStatsChange.from_dict(c)
        for c in changes
    ]
    batch = get_dashboard_stats_batch()
    if batch is not None:
        batch.add_changes(parsed)
        return

    deltas = merge_establishment_changes(parsed)
    schedule_dashboard_establishment_stats_deltas(tenant_id, deltas, countdown=countdown)


def schedule_dashboard_establishment_stats_refresh(
    tenant_id: UUID,
    establishment_ids: Iterable[int],
    *,
    countdown: int = 8,
) -> None:
    unique_ids = sorted({int(eid) for eid in establishment_ids if eid})
    if not unique_ids:
        return
    to_queue = [
        eid
        for eid in unique_ids
        if _try_acquire(dashboard_stats_queue_key(tenant_id, eid), _QUEUE_TTL_SECONDS)
    ]
    if not to_queue:
        return
    try:
        from app.tasks.dashboard_establishment_stats import (
            refresh_dashboard_establishment_stats_bulk_task,
            refresh_dashboard_establishment_stats_task,
        )

        if len(to_queue) == 1:
            eid = to_queue[0]
            refresh_dashboard_establishment_stats_task.apply_async(
                args=[str(tenant_id), eid],
                countdown=countdown,
                expires=max(countdown + 600, 900),
            )
        else:
            refresh_dashboard_establishment_stats_bulk_task.apply_async(
                args=[str(tenant_id), to_queue],
                countdown=countdown,
                expires=max(countdown + 600, 900),
            )
    except Exception as exc:  # noqa: BLE001
        for eid in to_queue:
            release_dashboard_stats_lock(dashboard_stats_queue_key(tenant_id, eid))
        logger.warning("No se pudo encolar refresh dashboard establishment stats: %s", exc)


def schedule_dashboard_establishment_stats_tenant_refresh(
    tenant_id: UUID,
    *,
    countdown: int = 5,
) -> None:
    if not _try_acquire(dashboard_stats_queue_key(tenant_id), _QUEUE_TTL_SECONDS):
        return
    try:
        from app.tasks.dashboard_establishment_stats import refresh_dashboard_establishment_stats_tenant_task

        refresh_dashboard_establishment_stats_tenant_task.apply_async(
            args=[str(tenant_id)],
            countdown=countdown,
            expires=max(countdown + 600, 900),
        )
    except Exception as exc:  # noqa: BLE001
        release_dashboard_stats_lock(dashboard_stats_queue_key(tenant_id))
        logger.warning("No se pudo encolar refresh dashboard stats tenant: %s", exc)


def schedule_dashboard_stats_after_card_item_change(
    db: Session,
    tenant_id: UUID,
    *,
    card_id: int,
    changes: list[Any],
) -> None:
    """Aplica deltas incrementales para el local de la hoja (+ opcional segundo local Margesi)."""
    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        EstablishmentStatsChange,
    )

    if changes:
        schedule_dashboard_establishment_stats_incremental(tenant_id, changes)
        return
    # Fallback: recalcular local si no se pasaron transiciones explícitas.
    ids = establishment_ids_for_card(db, tenant_id, card_id)
    schedule_dashboard_establishment_stats_refresh(tenant_id, ids)


def schedule_dashboard_stats_after_item_move(
    db: Session,
    tenant_id: UUID,
    *,
    old_card_id: int,
    new_card_id: int,
    item_inv_sit: str | None,
) -> None:
    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        change_for_establishment,
        itemcard_create_transition,
        itemcard_delete_transition,
    )

    old_ids = establishment_ids_for_card(db, tenant_id, old_card_id)
    new_ids = establishment_ids_for_card(db, tenant_id, new_card_id)
    if not old_ids or not new_ids:
        schedule_dashboard_establishment_stats_refresh(
            tenant_id,
            set(old_ids) | set(new_ids),
        )
        return
    old_est, new_est = old_ids[0], new_ids[0]
    if old_est == new_est:
        return
    changes = [
        change_for_establishment(old_est, itemcard_delete_transition(item_inv_sit)),
        change_for_establishment(new_est, itemcard_create_transition(item_inv_sit)),
    ]
    schedule_dashboard_establishment_stats_incremental(tenant_id, changes)


def schedule_dashboard_stats_after_conciliation(
    db: Session,
    tenant_id: UUID,
    *,
    marg: m.InvMargesiItem,
    bien: m.InvItemCard,
    marg_inv_sit_before: str | None,
    bien_inv_sit_before: str | None,
) -> None:
    from collections import defaultdict

    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        EntityTransition,
        change_for_establishment,
        itemcard_update_transition,
        margesi_update_transition,
    )

    marg_tr = margesi_update_transition(marg_inv_sit_before, marg.inv_sit)
    item_tr = itemcard_update_transition(bien_inv_sit_before, bien.inv_sit)
    by_est: dict[int, list[EntityTransition]] = defaultdict(list)

    for est_id in establishment_ids_for_margesi(db, tenant_id, marg):
        by_est[int(est_id)].append(marg_tr)
    for est_id in establishment_ids_for_item_card(db, tenant_id, bien):
        by_est[int(est_id)].append(item_tr)

    if not by_est:
        return
    changes = [
        change_for_establishment(est_id, *transitions)
        for est_id, transitions in by_est.items()
    ]
    schedule_dashboard_establishment_stats_incremental(tenant_id, changes)


def schedule_dashboard_stats_for_margesi_only(
    db: Session,
    tenant_id: UUID,
    *,
    marg: m.InvMargesiItem,
    inv_sit_before: str | None,
) -> None:
    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        change_for_establishment,
        margesi_update_transition,
    )

    est_ids = establishment_ids_for_margesi(db, tenant_id, marg)
    if not est_ids:
        return
    tr = margesi_update_transition(inv_sit_before, marg.inv_sit)
    schedule_dashboard_establishment_stats_incremental(
        tenant_id,
        [change_for_establishment(est_ids[0], tr)],
    )


def schedule_dashboard_stats_for_itemcard_only(
    db: Session,
    tenant_id: UUID,
    *,
    item: m.InvItemCard,
    card_id: int,
    inv_sit_before: str | None,
) -> None:
    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        change_for_establishment,
        itemcard_update_transition,
    )

    est_ids = establishment_ids_for_card(db, tenant_id, card_id)
    if not est_ids:
        return
    tr = itemcard_update_transition(inv_sit_before, item.inv_sit)
    schedule_dashboard_establishment_stats_incremental(
        tenant_id,
        [change_for_establishment(est_ids[0], tr)],
    )


def maybe_schedule_dashboard_stats_after_import(module: str, tenant_id: UUID) -> None:
    """Legacy: los imports encolan deltas incrementales por su cuenta."""
    _ = (module, tenant_id)


def dashboard_establishment_stats_cache_count(db: Session, tenant_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(m.InvDashboardEstablishmentStat)
            .where(m.InvDashboardEstablishmentStat.tenant_id == tenant_id),
        )
        or 0,
    )
