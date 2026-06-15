"""Diagnóstico: por qué margesi faltantes no entran en reporte_aptot_cache."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text

from app.db.session import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        tid = db.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
        t = str(tid)
        print(f"tenant_id: {t}\n")

        row = db.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE inv_sit IS NULL) AS sit_null,
                    COUNT(*) FILTER (WHERE TRIM(inv_sit) = 'N') AS sit_n,
                    COUNT(*) FILTER (WHERE TRIM(inv_sit) = 'C') AS sit_c,
                    COUNT(*) FILTER (WHERE TRIM(inv_sit) = 'S') AS sit_s,
                    COUNT(*) FILTER (WHERE inv_sit IS NOT NULL AND TRIM(inv_sit) NOT IN ('N','C','S','')) AS sit_other
                FROM margesi
                WHERE tenant_id = CAST(:t AS uuid)
                """
            ),
            {"t": t},
        ).one()
        print("=== margesi (totales) ===")
        for k, v in row._mapping.items():
            print(f"  {k}: {v}")

        linked = db.execute(
            text(
                """
                SELECT COUNT(DISTINCT m.id)
                FROM margesi m
                INNER JOIN itemcards ic ON ic.id_margesi = m.id AND ic.tenant_id = m.tenant_id
                WHERE m.tenant_id = CAST(:t AS uuid)
                """
            ),
            {"t": t},
        ).scalar()
        print(f"\nmargesi vinculados a itemcards: {linked}")

        faltante = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM margesi m
                WHERE m.tenant_id = CAST(:t AS uuid)
                  AND NOT EXISTS (
                      SELECT 1 FROM itemcards ic
                      WHERE ic.tenant_id = m.tenant_id AND ic.id_margesi = m.id
                  )
                  AND NOT (
                      UPPER(TRIM(COALESCE(m.inv_sit, ''))) = 'C'
                      AND NULLIF(TRIM(COALESCE(m.inv_num, '')), '') IS NOT NULL
                  )
                """
            ),
            {"t": t},
        ).scalar()
        print(f"faltantes (filtro actual): {faltante}")

        faltante_no_link = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM margesi m
                WHERE m.tenant_id = CAST(:t AS uuid)
                  AND NOT EXISTS (
                      SELECT 1 FROM itemcards ic
                      WHERE ic.tenant_id = m.tenant_id AND ic.id_margesi = m.id
                  )
                """
            ),
            {"t": t},
        ).scalar()
        print(f"margesi sin vinculo itemcard (cualquier inv_sit): {faltante_no_link}")

        faltante_null_only = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM margesi m
                WHERE m.tenant_id = CAST(:t AS uuid)
                  AND m.inv_sit IS NULL
                """
            ),
            {"t": t},
        ).scalar()
        print(f"margesi inv_sit IS NULL (sin mas filtros): {faltante_null_only}")

        print("\n=== inv_sit valores distintos (top 15) ===")
        samples = db.execute(
            text(
                """
                SELECT COALESCE(inv_sit, '<NULL>') AS v, COUNT(*) AS c
                FROM margesi
                WHERE tenant_id = CAST(:t AS uuid)
                GROUP BY 1
                ORDER BY c DESC
                LIMIT 15
                """
            ),
            {"t": t},
        ).all()
        for v, c in samples:
            print(f"  {repr(v)}: {c}")

        print("\n=== itemcards inv_sit ===")
        itc = db.execute(
            text(
                """
                SELECT COALESCE(NULLIF(TRIM(inv_sit), ''), '<NULL/empty>') AS v, COUNT(*) AS c
                FROM itemcards
                WHERE tenant_id = CAST(:t AS uuid)
                GROUP BY 1
                ORDER BY c DESC
                """
            ),
            {"t": t},
        ).all()
        for v, c in itc:
            print(f"  {repr(v)}: {c}")

        print("\n=== cache actual ===")
        cache = db.execute(
            text(
                """
                SELECT source_kind, COUNT(*)
                FROM reporte_aptot_cache
                WHERE tenant_id = CAST(:t AS uuid)
                GROUP BY 1
                ORDER BY 1
                """
            ),
            {"t": t},
        ).all()
        for sk, c in cache:
            print(f"  {sk}: {c}")


if __name__ == "__main__":
    main()
