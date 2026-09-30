"""Ejecución de una exportación en el worker: genera en streaming a disco, informa progreso y sube el archivo."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from app.db.copy_compat import copy_to, render_sql
from app.modules.exports import live, service
from app.modules.exports.specs import StoredOutput, get_spec

logger = logging.getLogger(__name__)

BOM = b"\xef\xbb\xbf"
PROGRESS_EVERY_ROWS = 5000
PROGRESS_MIN_SECONDS = 1.0
HEARTBEAT_SECONDS = 30.0
DB_TOUCH_SECONDS = 60.0


class ExportContext:
    """Herramientas para los generadores: COPY a disco con progreso, conversión a Excel y latidos."""

    def __init__(self, job_id: UUID, tenant_id: UUID, workdir: Path):
        self.job_id = job_id
        self.tenant_id = tenant_id
        self.workdir = workdir
        self._last_pct = 0
        self._last_live = 0.0
        self.last_message = ""

    def progress(
        self,
        pct: int,
        message: str,
        *,
        rows_done: int | None = None,
        rows_total: int | None = None,
        force: bool = False,
    ) -> None:
        pct = max(self._last_pct, min(int(pct), 99))
        now = time.monotonic()
        # Como mucho un aviso por segundo (un COPY rápido produce miles de filas por segundo).
        if not force and now - self._last_live < PROGRESS_MIN_SECONDS:
            return
        self._last_pct = pct
        self._last_live = now
        self.last_message = message
        fields: dict[str, Any] = {"state": "processing", "progress": pct, "message": message}
        if rows_done is not None:
            fields["rows_done"] = rows_done
        if rows_total is not None:
            fields["rows_total"] = rows_total
        live.write_job(self.job_id, fields)
        overlay = live.read_job(self.job_id) or {}
        live.publish(self.tenant_id, self.job_id, _progress_event(self.job_id, overlay))

    @property
    def last_progress(self) -> int:
        return self._last_pct

    def count_rows(self, inner_sql: str, params: tuple) -> int | None:
        """Total para calcular el porcentaje (una consulta de conteo, mucho más barata que la exportación)."""
        from app.db.session import engine

        conn = engine.raw_connection()
        try:
            cur = conn.cursor()
            cur.execute(render_sql(conn, "SELECT count(*) FROM (" + inner_sql + ") AS export_count", params))
            (total,) = cur.fetchone()
            return int(total)
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo contar filas para el progreso", exc_info=True)
            return None
        finally:
            conn.rollback()
            conn.close()

    def copy_csv(
        self,
        inner_sql: str,
        params: tuple,
        *,
        name: str = "data.csv",
        bom: bool = True,
        header_spaces: bool = False,
        span: tuple[int, int] = (5, 80),
    ) -> Path:
        """``COPY (consulta) TO STDOUT`` escrito directo a un archivo: la memoria no crece con las filas."""
        from app.db.session import engine

        self.progress(span[0], "Preparando datos…", force=True)
        total = self.count_rows(inner_sql, params)
        path = self.workdir / name
        conn = engine.raw_connection()
        try:
            copy_sql = render_sql(
                conn,
                "COPY (" + inner_sql + ") TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')",
                params,
            )
            with path.open("wb") as fh:
                if bom:
                    fh.write(BOM)
                writer = _ProgressWriter(fh, self, total=total, span=span, header_spaces=header_spaces)
                copy_to(conn, copy_sql, writer)
                writer.flush()
            self.progress(span[1], f"{_fmt_int(writer.rows)} filas generadas", rows_done=writer.rows, rows_total=total)
        finally:
            conn.rollback()
            conn.close()
        return path

    def to_xlsx(self, csv_path: Path, convert: Callable[[bytes], bytes], name: str = "data.xlsx") -> Path:
        """Convierte a Excel con los estilos de siempre. Excel se arma en memoria (openpyxl): para
        volúmenes grandes el CSV es mucho más rápido."""
        self.progress(max(self._last_pct, 82), "Armando el Excel…", force=True)
        content = convert(csv_path.read_bytes())
        path = self.workdir / name
        path.write_bytes(content)
        csv_path.unlink(missing_ok=True)
        return path


class _Heartbeat:
    """Latido independiente del avance: en pasos largos sin progreso (armar un Excel grande, subir el
    archivo) el trabajo sigue constando como vivo y no se da por colgado."""

    def __init__(self, ctx: ExportContext):
        import threading

        self._ctx = ctx
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"export-hb-{ctx.job_id}", daemon=True)

    def __enter__(self) -> "_Heartbeat":
        live.heartbeat(self._ctx.job_id)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        last_db = time.monotonic()
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                live.heartbeat(self._ctx.job_id)
                if time.monotonic() - last_db >= DB_TOUCH_SECONDS:
                    last_db = time.monotonic()
                    service.touch(
                        self._ctx.job_id,
                        self._ctx.tenant_id,
                        self._ctx.last_progress,
                        self._ctx.last_message or "Generando…",
                    )
            except Exception:  # noqa: BLE001
                logger.warning("Fallo el latido de la exportación %s", self._ctx.job_id, exc_info=True)


class _ProgressWriter:
    """Destino del COPY: escribe en disco y reporta avance cada ``PROGRESS_EVERY_ROWS`` filas."""

    def __init__(self, fh, ctx: ExportContext, *, total: int | None, span: tuple[int, int], header_spaces: bool):
        self._fh = fh
        self._ctx = ctx
        self._total = total
        self._span = span
        self._header_pending = header_spaces
        self._header_buf = b""
        self._newlines = 0
        self._next_report = PROGRESS_EVERY_ROWS

    @property
    def rows(self) -> int:
        # La primera línea es la cabecera. Aproximado si un campo trae saltos de línea (solo para el avance).
        return max(self._newlines - 1, 0)

    def write(self, data) -> int:
        if isinstance(data, str):
            data = data.encode("utf-8")
        if self._header_pending:
            # Cabecera con espacios en vez de "_" (formato histórico del reporte APTOT).
            self._header_buf += data
            idx = self._header_buf.find(b"\n")
            if idx < 0:
                return len(data)
            header, rest = self._header_buf[: idx + 1], self._header_buf[idx + 1 :]
            self._header_pending = False
            self._header_buf = b""
            chunk = header.replace(b"_", b" ") + rest
        else:
            chunk = data
        self._fh.write(chunk)
        self._newlines += chunk.count(b"\n")
        if self.rows >= self._next_report:
            self._next_report = self.rows + PROGRESS_EVERY_ROWS
            self._report()
        return len(data)

    def flush(self) -> None:
        if self._header_buf:
            self._fh.write(self._header_buf.replace(b"_", b" "))
            self._header_buf = b""

    def _report(self) -> None:
        lo, hi = self._span
        if self._total:
            pct = lo + int((hi - lo) * min(self.rows / self._total, 1))
            msg = f"Generando {_fmt_int(self.rows)} de {_fmt_int(self._total)} filas…"
        else:
            pct = lo + min(self.rows // 20000, hi - lo - 1)
            msg = f"Generando… {_fmt_int(self.rows)} filas"
        self._ctx.progress(pct, msg, rows_done=self.rows, rows_total=self._total)


def _fmt_int(n: int | None) -> str:
    return f"{n or 0:,}".replace(",", ".")


def _progress_event(job_id: UUID, overlay: dict[str, str]) -> dict[str, Any]:
    """Evento liviano de progreso (sin tocar la base)."""
    return {
        "job_id": str(job_id),
        "module": overlay.get("module"),
        "label": overlay.get("label"),
        "format": overlay.get("format"),
        "state": overlay.get("state") or "processing",
        "progress": int(overlay.get("progress") or 0),
        "message": overlay.get("message") or "",
        "rows_done": int(overlay["rows_done"]) if overlay.get("rows_done") else None,
        "rows_total": int(overlay["rows_total"]) if overlay.get("rows_total") else None,
        "partial": True,
    }


def run_export_job(job_id: str, tenant_id: str, module: str, params: dict[str, Any], export_format: str) -> dict:
    """Punto de entrada del worker (Celery o hilo en desarrollo)."""
    from app.core.export_storage import resolve_download_url, upload_export_path

    job_uuid = UUID(job_id)
    tenant_uuid = UUID(tenant_id)
    try:
        spec = get_spec(module)
    except LookupError as exc:
        service.mark_failure(job_uuid, tenant_uuid, str(exc))
        return {"success": False, "message": str(exc)}

    first = "Generando Excel…" if export_format == "xlsx" else "Empaquetando archivos…" if export_format == "zip" else "Generando CSV…"
    if not service.mark_processing(job_uuid, tenant_uuid, first):
        return {"success": False, "message": "Trabajo inexistente o ya finalizado"}

    try:
        with tempfile.TemporaryDirectory(prefix=f"export_{module}_") as tmp:
            ctx = ExportContext(job_uuid, tenant_uuid, Path(tmp))
            with _Heartbeat(ctx):
                result = spec.generate(ctx, tenant_uuid, params, export_format)
                if isinstance(result, StoredOutput):
                    # Escrito en streaming directo al almacenamiento por el generador.
                    storage_path, filename, size = result.storage_path, result.filename, result.size
                else:
                    path, filename = result
                    size = path.stat().st_size
                    ctx.progress(90, f"Subiendo archivo ({size / 1024 / 1024:.1f} MB)…", force=True)
                    storage_path = upload_export_path(
                        module=module,
                        tenant_id=tenant_uuid,
                        job_id=job_uuid,
                        filename=filename,
                        file_path=path,
                    )
        download_url, expires_at = resolve_download_url(storage_path=storage_path, filename=filename, job_id=job_uuid)
        service.mark_success(
            job_uuid,
            tenant_uuid,
            filename=filename,
            storage_path=storage_path,
            download_url=download_url,
            expires_at=expires_at,
            file_size_bytes=size,
            message="Archivo listo para descargar",
        )
        return {"success": True, "job_id": job_id, "filename": filename, "file_size_bytes": size}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Exportación %s (%s) falló", job_id, module)
        message = str(exc)[:500] or "La exportación falló"
        service.mark_failure(job_uuid, tenant_uuid, message)
        return {"success": False, "job_id": job_id, "message": message}
