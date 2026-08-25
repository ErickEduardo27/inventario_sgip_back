"""Actualización incremental de ``dashboard_establishment_stats`` (sin COUNT masivo)."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.inventory import models as m

_MARGESI_FALTANTE = frozenset({"-", "—", "–"})

_dashboard_stats_batch: ContextVar["DashboardStatsBatchCollector | None"] = ContextVar(
    "dashboard_stats_batch",
    default=None,
)

_ITEMCARD_FIELDS = (
    "inventario_total",
    "inventario_conciliado",
    "inventario_sobrante",
    "inventario_no_conciliable",
)
_MARGESI_FIELDS = (
    "margesi_total",
    "margesi_conciliado",
    "margesi_faltantes",
    "margesi_no_inventariable",
)
_ALL_COUNTER_FIELDS = _ITEMCARD_FIELDS + _MARGESI_FIELDS


def _zero_counters() -> dict[str, int]:
    return dict.fromkeys(_ALL_COUNTER_FIELDS, 0)


def _is_margesi_faltante(inv_sit: str | None) -> bool:
    if inv_sit is None:
        return True
    s = str(inv_sit).strip()
    if not s:
        return True
    return s in _MARGESI_FALTANTE


def itemcard_counter_values(inv_sit: str | None) -> dict[str, int]:
    """Contadores que aporta un ítem de inventario según ``inv_sit``."""
    counts = _zero_counters()
    counts["inventario_total"] = 1
    sit = (inv_sit or "").strip().upper()
    if sit == "C":
        counts["inventario_conciliado"] = 1
    elif sit == "S":
        counts["inventario_sobrante"] = 1
    elif sit == "N":
        counts["inventario_no_conciliable"] = 1
    return counts


def margesi_counter_values(inv_sit: str | None) -> dict[str, int]:
    """Contadores que aporta una fila Margesi según ``inv_sit``."""
    counts = _zero_counters()
    counts["margesi_total"] = 1
    sit = (inv_sit or "").strip().upper()
    if sit == "C":
        counts["margesi_conciliado"] = 1
    elif sit == "N":
        counts["margesi_no_inventariable"] = 1
    elif _is_margesi_faltante(inv_sit):
        counts["margesi_faltantes"] = 1
    return counts


def entity_transition_delta(
    *,
    exists_before: bool,
    inv_sit_before: str | None,
    exists_after: bool,
    inv_sit_after: str | None,
    kind: Literal["itemcard", "margesi"],
) -> dict[str, int]:
    """Delta de contadores entre dos estados de una entidad (crear / editar / eliminar)."""
    classify = itemcard_counter_values if kind == "itemcard" else margesi_counter_values
    before = classify(inv_sit_before) if exists_before else _zero_counters()
    after = classify(inv_sit_after) if exists_after else _zero_counters()
    return {field: after[field] - before[field] for field in _ALL_COUNTER_FIELDS if after[field] != before[field]}


@dataclass(frozen=True)
class EntityTransition:
    """Transición de contadores para itemcard o margesi en un local."""

    kind: Literal["itemcard", "margesi"]
    exists_before: bool
    inv_sit_before: str | None
    exists_after: bool
    inv_sit_after: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "exists_before": self.exists_before,
            "inv_sit_before": self.inv_sit_before,
            "exists_after": self.exists_after,
            "inv_sit_after": self.inv_sit_after,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EntityTransition:
        return cls(
            kind=raw["kind"],
            exists_before=bool(raw["exists_before"]),
            inv_sit_before=raw.get("inv_sit_before"),
            exists_after=bool(raw["exists_after"]),
            inv_sit_after=raw.get("inv_sit_after"),
        )

    def delta(self) -> dict[str, int]:
        return entity_transition_delta(
            exists_before=self.exists_before,
            inv_sit_before=self.inv_sit_before,
            exists_after=self.exists_after,
            inv_sit_after=self.inv_sit_after,
            kind=self.kind,
        )


@dataclass(frozen=True)
class EstablishmentStatsChange:
    establishment_id: int
    transitions: tuple[EntityTransition, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "establishment_id": self.establishment_id,
            "transitions": [t.to_dict() for t in self.transitions],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EstablishmentStatsChange:
        return cls(
            establishment_id=int(raw["establishment_id"]),
            transitions=tuple(EntityTransition.from_dict(t) for t in raw.get("transitions") or []),
        )

    def merged_delta(self) -> dict[str, int]:
        merged: dict[str, int] = defaultdict(int)
        for transition in self.transitions:
            for field, value in transition.delta().items():
                merged[field] += value
        return dict(merged)


def merge_establishment_changes(changes: list[EstablishmentStatsChange]) -> dict[int, dict[str, int]]:
    """Combina varios cambios (p. ej. conciliación en dos locales) por ``establishment_id``."""
    by_est: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for change in changes:
        for field, value in change.merged_delta().items():
            by_est[change.establishment_id][field] += value
    return {est_id: dict(deltas) for est_id, deltas in by_est.items() if any(deltas.values())}


def _ensure_stats_row(db: Session, tenant_id: UUID, establishment_id: int) -> m.InvDashboardEstablishmentStat:
    row = db.scalar(
        select(m.InvDashboardEstablishmentStat).where(
            m.InvDashboardEstablishmentStat.tenant_id == tenant_id,
            m.InvDashboardEstablishmentStat.establishment_id == establishment_id,
        ),
    )
    if row is not None:
        return row

    est = db.get(m.InvEstablishment, establishment_id)
    if est is None or est.tenant_id != tenant_id:
        raise ValueError(f"Local {establishment_id} no encontrado")

    now = datetime.now(timezone.utc)
    row = m.InvDashboardEstablishmentStat(
        tenant_id=tenant_id,
        establishment_id=establishment_id,
        establishment_code=str(est.code or ""),
        establishment_description=est.description,
        refreshed_at=now,
    )
    db.add(row)
    db.flush()
    return row


def apply_establishment_deltas(
    db: Session,
    tenant_id: UUID,
    deltas_by_establishment: dict[int, dict[str, int]],
) -> int:
    """Aplica deltas ``+=`` sobre ``dashboard_establishment_stats`` (operación O(1) por local)."""
    if not deltas_by_establishment:
        return 0

    updated = 0
    now = datetime.now(timezone.utc)
    for est_id, deltas in deltas_by_establishment.items():
        if not any(deltas.values()):
            continue
        row = _ensure_stats_row(db, tenant_id, int(est_id))
        for field in _ALL_COUNTER_FIELDS:
            delta = int(deltas.get(field, 0))
            if delta == 0:
                continue
            current = int(getattr(row, field, 0) or 0)
            setattr(row, field, max(0, current + delta))
        row.refreshed_at = now
        db.add(row)
        updated += 1
    if updated:
        db.commit()
    return updated


def apply_establishment_stats_changes(
    db: Session,
    tenant_id: UUID,
    changes: list[EstablishmentStatsChange],
) -> int:
    deltas = merge_establishment_changes(changes)
    return apply_establishment_deltas(db, tenant_id, deltas)


def itemcard_create_transition(inv_sit: str | None) -> EntityTransition:
    return EntityTransition("itemcard", False, None, True, inv_sit)


def itemcard_delete_transition(inv_sit: str | None) -> EntityTransition:
    return EntityTransition("itemcard", True, inv_sit, False, None)


def itemcard_update_transition(before: str | None, after: str | None) -> EntityTransition:
    return EntityTransition("itemcard", True, before, True, after)


def margesi_update_transition(before: str | None, after: str | None) -> EntityTransition:
    return EntityTransition("margesi", True, before, True, after)


def change_for_establishment(
    establishment_id: int,
    *transitions: EntityTransition,
) -> EstablishmentStatsChange:
    return EstablishmentStatsChange(establishment_id, transitions)


@dataclass
class DashboardStatsBatchCollector:
    """Acumula deltas durante imports masivos; un solo flush a Celery al final."""

    _deltas: dict[int, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))

    def merge_deltas(self, deltas_by_establishment: dict[int, dict[str, int]]) -> None:
        for est_id, deltas in deltas_by_establishment.items():
            for field, value in deltas.items():
                if value:
                    self._deltas[int(est_id)][field] += int(value)

    def add_change(self, change: EstablishmentStatsChange) -> None:
        self.merge_deltas({change.establishment_id: change.merged_delta()})

    def add_changes(self, changes: list[EstablishmentStatsChange]) -> None:
        self.merge_deltas(merge_establishment_changes(changes))

    def add_transition(self, establishment_id: int, transition: EntityTransition) -> None:
        self.merge_deltas({establishment_id: transition.delta()})

    def add_transitions(self, establishment_id: int, *transitions: EntityTransition) -> None:
        merged: dict[str, int] = defaultdict(int)
        for transition in transitions:
            for field, value in transition.delta().items():
                merged[field] += value
        self.merge_deltas({establishment_id: dict(merged)})

    def merged_deltas(self) -> dict[int, dict[str, int]]:
        return {
            est_id: dict(deltas)
            for est_id, deltas in self._deltas.items()
            if any(deltas.values())
        }

    def is_empty(self) -> bool:
        return not self.merged_deltas()


def get_dashboard_stats_batch() -> DashboardStatsBatchCollector | None:
    return _dashboard_stats_batch.get()


@contextmanager
def dashboard_stats_batch() -> Iterator[DashboardStatsBatchCollector]:
    """Agrupa deltas de operaciones repetidas (p. ej. import hoja captura) en un solo job."""
    collector = DashboardStatsBatchCollector()
    token = _dashboard_stats_batch.set(collector)
    try:
        yield collector
    finally:
        _dashboard_stats_batch.reset(token)


def ensure_stats_rows_for_establishments_without_cache(
    db: Session,
    tenant_id: UUID,
    *,
    establishment_ids: list[int] | None = None,
) -> int:
    """Crea filas en cero para locales nuevos (imports de establishments)."""
    stmt = select(m.InvEstablishment.id).where(m.InvEstablishment.tenant_id == tenant_id)
    if establishment_ids:
        stmt = stmt.where(m.InvEstablishment.id.in_(establishment_ids))
    est_ids = list(db.scalars(stmt).all())
    created = 0
    for est_id in est_ids:
        existing = db.scalar(
            select(m.InvDashboardEstablishmentStat.id).where(
                m.InvDashboardEstablishmentStat.tenant_id == tenant_id,
                m.InvDashboardEstablishmentStat.establishment_id == int(est_id),
            ),
        )
        if existing is not None:
            continue
        _ensure_stats_row(db, tenant_id, int(est_id))
        created += 1
    if created:
        db.commit()
    return created


def collect_margesi_staging_deltas(
    db: Session,
    tenant_id: UUID,
    *,
    staging_table: str = "tmp_margesi_staging",
) -> dict[int, dict[str, int]]:
    """Calcula deltas Margesi de un chunk staging (antes debe existir ``{staging}_before``)."""
    before_table = f"{staging_table}_stats_before"
    sql = text(
        f"""
        WITH staged AS (
            SELECT DISTINCT NULLIF(TRIM(mar_num), '') AS mar_num
            FROM {staging_table}
            WHERE NULLIF(TRIM(mar_num), '') IS NOT NULL
        ),
        paired AS (
            SELECT
                e.id AS establishment_id,
                b.inv_sit AS before_sit,
                m.inv_sit AS after_sit,
                (b.mar_num IS NULL) AS is_insert
            FROM staged s
            INNER JOIN margesi m
                ON m.tenant_id = CAST(:tenant_id AS uuid)
               AND m.mar_num = s.mar_num
            LEFT JOIN {before_table} b ON b.mar_num = s.mar_num
            LEFT JOIN establishments e
                ON e.tenant_id = m.tenant_id
               AND e.code = m.amb_cod
            WHERE e.id IS NOT NULL
        )
        SELECT establishment_id, before_sit, after_sit, is_insert
        FROM paired
        """
    )
    rows = db.execute(sql, {"tenant_id": str(tenant_id)}).mappings().all()
    by_est: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        est_id = int(row["establishment_id"])
        if row["is_insert"]:
            delta = entity_transition_delta(
                exists_before=False,
                inv_sit_before=None,
                exists_after=True,
                inv_sit_after=row["after_sit"],
                kind="margesi",
            )
        else:
            delta = entity_transition_delta(
                exists_before=True,
                inv_sit_before=row["before_sit"],
                exists_after=True,
                inv_sit_after=row["after_sit"],
                kind="margesi",
            )
        for field, value in delta.items():
            by_est[est_id][field] += value
    return {est_id: dict(deltas) for est_id, deltas in by_est.items()}


def collect_margesi_null_mar_num_insert_deltas(
    db: Session,
    tenant_id: UUID,
    *,
    row_count: int,
    amb_codes: list[str],
) -> dict[int, dict[str, int]]:
    """Altas Margesi sin ``mar_num``: cada fila importada suma contadores faltantes por local."""
    if row_count <= 0 or not amb_codes:
        return {}
    by_code: dict[str, int] = defaultdict(int)
    for code in amb_codes:
        c = (code or "").strip()
        if c:
            by_code[c] += 1
    if not by_code:
        return {}
    est_rows = db.execute(
        text(
            """
            SELECT id, code
            FROM establishments
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND code = ANY(:codes)
            """
        ),
        {"tenant_id": str(tenant_id), "codes": list(by_code.keys())},
    ).mappings().all()
    code_to_est = {str(r["code"]): int(r["id"]) for r in est_rows}
    by_est: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    faltante = margesi_counter_values(None)
    for code, count in by_code.items():
        est_id = code_to_est.get(code)
        if est_id is None:
            continue
        for field, unit in faltante.items():
            if unit:
                by_est[est_id][field] += unit * count
    return {est_id: dict(deltas) for est_id, deltas in by_est.items()}


def collect_cards_ambiente_move_deltas(
    db: Session,
    tenant_id: UUID,
    *,
    staging_table: str = "tmp_cards_import",
    before_table: str = "tmp_cards_est_before",
) -> dict[int, dict[str, int]]:
    """Si el import cambió ``id_ambiente`` de hojas, mueve contadores de bienes entre locales."""
    sql = text(
        f"""
        SELECT
            ic.inv_sit,
            b.establishment_id AS old_establishment_id,
            env.establishment_id AS new_establishment_id
        FROM itemcards ic
        INNER JOIN cards c
            ON c.id = ic.id_card
           AND c.tenant_id = ic.tenant_id
        INNER JOIN {before_table} b
            ON b.card_id = c.id
        INNER JOIN enviroments env
            ON env.id = c.id_ambiente
           AND env.tenant_id = c.tenant_id
        WHERE ic.tenant_id = CAST(:tenant_id AS uuid)
          AND b.establishment_id IS NOT NULL
          AND env.establishment_id IS NOT NULL
          AND b.establishment_id <> env.establishment_id
        """
    )
    rows = db.execute(sql, {"tenant_id": str(tenant_id)}).mappings().all()
    by_est: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        inv_sit = row["inv_sit"]
        old_est = int(row["old_establishment_id"])
        new_est = int(row["new_establishment_id"])
        remove = entity_transition_delta(
            exists_before=True,
            inv_sit_before=inv_sit,
            exists_after=False,
            inv_sit_after=None,
            kind="itemcard",
        )
        add = entity_transition_delta(
            exists_before=False,
            inv_sit_before=None,
            exists_after=True,
            inv_sit_after=inv_sit,
            kind="itemcard",
        )
        for field, value in remove.items():
            by_est[old_est][field] += value
        for field, value in add.items():
            by_est[new_est][field] += value
    return {est_id: dict(deltas) for est_id, deltas in by_est.items()}
