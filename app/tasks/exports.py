"""Tarea Celery única para todas las exportaciones (ver ``app.modules.exports``).

Worker dedicado recomendado (no compite con importaciones ni envíos programados):

    EXPORT_CELERY_QUEUE=exports
    celery -A app.celery_app:celery_app worker -Q exports -c 2 -n exports@%h

``-c 2`` limita las exportaciones simultáneas: una ráfaga de pedidos espera en cola en vez de saturar la base.
"""

from __future__ import annotations

from app.celery_app import celery_app
from app.modules.exports.runner import run_export_job


@celery_app.task(
    name="export.run",
    acks_late=True,
    # Una exportación colgada no retiene el worker para siempre.
    soft_time_limit=45 * 60,
    time_limit=50 * 60,
)
def run_export_task(job_id: str, tenant_id: str, module: str, params: dict, export_format: str) -> dict:
    return run_export_job(job_id, tenant_id, module, params, export_format)
