#!/usr/bin/env python3
"""
Reconstruye ``reporte_aptot_cache`` con todos los bienes, hojas y margesi existentes.

Uso (desde la carpeta ``back``, con venv activo):

    # Todos los tenants
    python scripts/rebuild_reporte_aptot_cache.py

    # Un tenant específico
    python scripts/rebuild_reporte_aptot_cache.py --tenant-id d026dc3e-a873-4a73-9e9e-855aea0eeed4

    # Listar tenants disponibles
    python scripts/rebuild_reporte_aptot_cache.py --list-tenants
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from uuid import UUID

# Raíz del proyecto ``back`` en sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.modules.inventory.reporte_aptot_cache import rebuild_reporte_aptot_cache
from app.modules.tenants.models import Tenant


def _list_tenants() -> list[tuple[UUID, str, str]]:
    with SessionLocal() as db:
        rows = db.execute(select(Tenant.id, Tenant.name, Tenant.slug).order_by(Tenant.name)).all()
    return [(row[0], row[1], row[2]) for row in rows]


def _rebuild_one(tenant_id: UUID, label: str) -> dict:
    started = time.perf_counter()
    print(f"\n>> Tenant: {label} ({tenant_id})")
    with SessionLocal() as db:
        result = rebuild_reporte_aptot_cache(db, tenant_id)
    elapsed = time.perf_counter() - started
    print(
        f"  OK {result['row_count']:,} filas | "
        f"actualizado: {result['refreshed_at']} | "
        f"{elapsed:.1f}s"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Poblar/actualizar reporte_aptot_cache con bienes, hojas y margesi existentes.",
    )
    parser.add_argument(
        "--tenant-id",
        help="UUID del tenant. Si se omite, procesa todos los tenants activos.",
    )
    parser.add_argument(
        "--list-tenants",
        action="store_true",
        help="Lista tenants y termina.",
    )
    args = parser.parse_args()

    if args.list_tenants:
        tenants = _list_tenants()
        if not tenants:
            print("No hay tenants en la base de datos.")
            return 1
        print("Tenants disponibles:")
        for tid, name, slug in tenants:
            print(f"  {tid}  {slug}  ({name})")
        return 0

    if args.tenant_id:
        try:
            tenant_uuid = UUID(args.tenant_id)
        except ValueError:
            print(f"UUID inválido: {args.tenant_id}", file=sys.stderr)
            return 1
        tenants = [t for t in _list_tenants() if t[0] == tenant_uuid]
        if not tenants:
            with SessionLocal() as db:
                exists = db.execute(
                    text("SELECT 1 FROM tenants WHERE id = CAST(:id AS uuid)"),
                    {"id": str(tenant_uuid)},
                ).scalar()
            if not exists:
                print(f"Tenant no encontrado: {tenant_uuid}", file=sys.stderr)
                return 1
            tenants = [(tenant_uuid, "(sin nombre)", "")]
        tid, name, slug = tenants[0]
        label = slug or name or str(tid)
        _rebuild_one(tid, label)
        print("\nListo.")
        return 0

    tenants = _list_tenants()
    if not tenants:
        print("No hay tenants en la base de datos.", file=sys.stderr)
        return 1

    print(f"Reconstruyendo cache APTOT para {len(tenants)} tenant(s)…")
    total_rows = 0
    for tid, name, slug in tenants:
        label = slug or name or str(tid)
        result = _rebuild_one(tid, label)
        total_rows += int(result["row_count"])

    print(f"\nListo. Total filas en cache: {total_rows:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
