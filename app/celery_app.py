"""Aplicación Celery: broker/resultado en Redis (local o remoto).

Arranque del worker (desde la carpeta `back`, con venv activo):

    celery -A app.celery_app:celery_app worker -l info

La API encola con ``apply_async(..., eta=...)`` al crear/reprogramar un envío
si ``CELERY_BROKER_URL`` está definido en ``.env``.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()
_broker = (_settings.celery_broker_url or "").strip() or "redis://127.0.0.1:6379/0"
_backend = (_settings.celery_result_backend or "").strip() or _broker

celery_app = Celery(
    "inventario_sgip",
    broker=_broker,
    backend=_backend,
    include=[
        "app.tasks.scheduled_dispatch",
        "app.tasks.establishment_import",
        "app.tasks.bulk_imports",
        "app.tasks.reporte_aptot",
        "app.tasks.dashboard_establishment_stats",
        "app.tasks.csv_exports",
        "app.tasks.reporte_locales_downloads",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    result_expires=3600,
)

# Registra tablas referenciadas por FKs (import_jobs → tenants, users).
from app.modules.iam import models as _iam_models  # noqa: F401, E402
from app.modules.inventory import models as _inventory_models  # noqa: F401, E402
from app.modules.tenants import models as _tenants_models  # noqa: F401, E402
