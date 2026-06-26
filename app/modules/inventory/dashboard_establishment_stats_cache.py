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

_ESTABLISHMENT_STATS_SQL = """
    SELECT
        e.id AS establishment_id,
        e.code AS establishment_code,
        e.description AS establishment_description,
        COUNT(DISTINCT marg.id) AS margesi_total,
        COUNT(DISTINCT marg.id) FILTER (WHERE marg.inv_sit = 'C') AS margesi_conciliado,
        COUNT(DISTINCT marg.id) FILTER (
            WHERE marg.inv_sit IS NULL
               OR TRIM(COALESCE(marg.inv_sit, '')) = ''
               OR marg.inv_sit IN ('-', '—', '–')
        ) AS margesi_faltantes,
        COUNT(DISTINCT marg.id) FILTER (WHERE marg.inv_sit = 'N') AS margesi_no_inventariable,
        COUNT(DISTINCT ic.id) AS inventario_total,
        COUNT(DISTINCT ic.id) FILTER (WHERE ic.inv_sit = 'C') AS inventario_conciliado,
        COUNT(DISTINCT ic.id) FILTER (WHERE ic.inv_sit = 'S') AS inventario_sobrante,
        COUNT(DISTINCT ic.id) FILTER (WHERE ic.inv_sit = 'N') AS inventario_no_conciliable
    FROM establishments e
    LEFT JOIN margesi marg
        ON marg.tenant_id = e.tenant_id AND marg.amb_cod = e.code
    LEFT JOIN enviroments env
        ON env.tenant_id = e.tenant_id AND env.establishment_id = e.id
    LEFT JOIN cards c
        ON c.tenant_id = e.tenant_id AND c.id_ambiente = env.id
    LEFT JOIN itemcards ic
        ON ic.tenant_id = c.tenant_id AND ic.id_card = c.id
    WHERE e.tenant_id = CAST(:tenant_id AS uuid)
      {establishment_filter}
    GROUP BY e.id, e.code, e.description
    ORDER BY e.code ASC
"""


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
        filt = "AND e.id = :establishment_id"
        bind: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "establishment_id": establishment_id,
        }
    else:
        filt = ""
        bind = {"tenant_id": str(tenant_id)}

    sql = _ESTABLISHMENT_STATS_SQL.format(establishment_filter=filt)
    rows = db.execute(text(sql), bind).mappings().all()
    return [_row_to_cache_dict(row, refreshed_at) for row in rows]


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


def schedule_dashboard_establishment_stats_refresh(
    tenant_id: UUID,
    establishment_ids: Iterable[int],
    *,
    countdown: int = 3,
) -> None:
    unique_ids = sorted({int(eid) for eid in establishment_ids if eid})
    if not unique_ids:
        return
    try:
        from app.tasks.dashboard_establishment_stats import (
            refresh_dashboard_establishment_stats_bulk_task,
            refresh_dashboard_establishment_stats_task,
        )

        if len(unique_ids) == 1:
            eid = unique_ids[0]
            refresh_dashboard_establishment_stats_task.apply_async(
                args=[str(tenant_id), eid],
                countdown=countdown,
            )
        else:
            refresh_dashboard_establishment_stats_bulk_task.apply_async(
                args=[str(tenant_id), unique_ids],
                countdown=countdown,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo encolar refresh dashboard establishment stats: %s", exc)


def schedule_dashboard_establishment_stats_tenant_refresh(
    tenant_id: UUID,
    *,
    countdown: int = 5,
) -> None:
    try:
        from app.tasks.dashboard_establishment_stats import refresh_dashboard_establishment_stats_tenant_task

        refresh_dashboard_establishment_stats_tenant_task.apply_async(
            args=[str(tenant_id)],
            countdown=countdown,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo encolar refresh dashboard stats tenant: %s", exc)


def schedule_dashboard_stats_after_card_item_change(
    db: Session,
    tenant_id: UUID,
    *,
    card_id: int,
    margesi_row: m.InvMargesiItem | None = None,
) -> None:
    ids = set(establishment_ids_for_card(db, tenant_id, card_id))
    if margesi_row is not None:
        ids.update(establishment_ids_for_margesi(db, tenant_id, margesi_row))
    schedule_dashboard_establishment_stats_refresh(tenant_id, ids)


def schedule_dashboard_stats_after_item_move(
    db: Session,
    tenant_id: UUID,
    *,
    old_card_id: int,
    new_card_id: int,
) -> None:
    ids = set(establishment_ids_for_card(db, tenant_id, old_card_id))
    ids.update(establishment_ids_for_card(db, tenant_id, new_card_id))
    schedule_dashboard_establishment_stats_refresh(tenant_id, ids)


def maybe_schedule_dashboard_stats_after_import(module: str, tenant_id: UUID) -> None:
    if module in DASHBOARD_STATS_IMPORT_MODULES:
        schedule_dashboard_establishment_stats_tenant_refresh(tenant_id)


def dashboard_establishment_stats_cache_count(db: Session, tenant_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(m.InvDashboardEstablishmentStat)
            .where(m.InvDashboardEstablishmentStat.tenant_id == tenant_id),
        )
        or 0,
    )
