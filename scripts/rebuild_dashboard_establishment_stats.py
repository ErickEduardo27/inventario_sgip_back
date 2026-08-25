"""Poblar o actualizar ``dashboard_establishment_stats`` para todos los locales.

Uso (desde ``back/``, con venv activo):

    python scripts/rebuild_dashboard_establishment_stats.py

    python scripts/rebuild_dashboard_establishment_stats.py --tenant-id <uuid>

    python scripts/rebuild_dashboard_establishment_stats.py --list-tenants
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.modules.inventory.dashboard_establishment_stats_cache import (
    rebuild_dashboard_establishment_stats_tenant,
)
from app.modules.tenants.models import Tenant


def _list_tenants() -> None:
    with SessionLocal() as db:
        rows = db.query(Tenant).order_by(Tenant.name).all()
        for t in rows:
            print(f"{t.id}\t{t.name}")


def _rebuild(tenant_id: UUID) -> None:
    with SessionLocal() as db:
        result = rebuild_dashboard_establishment_stats_tenant(db, tenant_id)
        print(result)


def _rebuild_all() -> None:
    with SessionLocal() as db:
        tenant_ids = [t.id for t in db.query(Tenant).order_by(Tenant.name).all()]
    if not tenant_ids:
        print("No hay tenants en la base.")
        return
    for tenant_id in tenant_ids:
        print(f"Reconstruyendo tenant {tenant_id}…")
        _rebuild(tenant_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poblar/actualizar dashboard_establishment_stats por tenant.",
    )
    parser.add_argument("--tenant-id", type=str, help="UUID del tenant (si se omite, reconstruye todos)")
    parser.add_argument("--list-tenants", action="store_true", help="Listar tenants")
    args = parser.parse_args()

    if args.list_tenants:
        _list_tenants()
        return

    if args.tenant_id:
        _rebuild(UUID(args.tenant_id))
        return

    _rebuild_all()


if __name__ == "__main__":
    main()
