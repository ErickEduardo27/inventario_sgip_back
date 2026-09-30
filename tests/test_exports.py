"""Pruebas de la lógica de exportaciones que no requiere base de datos ni Redis.

    venv/Scripts/python.exe -m unittest tests.test_exports -v
"""

from __future__ import annotations

import io
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from app.modules.exports import runner, service
from app.modules.exports.specs import get_spec, normalize_format


class RequestKeyTests(unittest.TestCase):
    tenant = uuid.uuid4()

    def _key(self, module: str, filters: dict, fmt: str = "csv") -> str:
        spec = get_spec(module)
        f, _run, key = service._prepare(spec, self.tenant, SimpleNamespace(id=None), filters, fmt)
        return key

    def test_same_filters_in_any_order_or_case_share_key(self):
        a = self._key("margesi", {"search": " Silla ", "local_code": "a01", "page": 3})
        b = self._key("margesi", {"local_code": "A01", "search": "silla", "page": 1, "per_page": 50})
        self.assertEqual(a, b, "la paginación y mayúsculas no deben cambiar el archivo")

    def test_format_and_filters_change_key(self):
        base = self._key("item_cards", {"inv_sit_filter": "C"})
        self.assertNotEqual(base, self._key("item_cards", {"inv_sit_filter": "C"}, "xlsx"))
        self.assertNotEqual(base, self._key("item_cards", {"inv_sit_filter": "S"}))

    def test_margesi_layout_is_part_of_key(self):
        self.assertNotEqual(
            self._key("margesi", {"export_layout": "report"}, "xlsx"),
            self._key("margesi", {"export_layout": "full"}, "xlsx"),
        )

    def test_tenants_never_share(self):
        spec = get_spec("persons")
        k1 = service._prepare(spec, uuid.uuid4(), SimpleNamespace(id=None), {}, "csv")[2]
        k2 = service._prepare(spec, uuid.uuid4(), SimpleNamespace(id=None), {}, "csv")[2]
        self.assertNotEqual(k1, k2)


class FormatAndParseTests(unittest.TestCase):
    def test_excel_alias_and_invalid_format(self):
        self.assertEqual(normalize_format(get_spec("persons"), "excel"), "xlsx")
        self.assertEqual(normalize_format(get_spec("hoja_captura"), None), "xlsx")
        with self.assertRaises(ValueError):
            normalize_format(get_spec("hoja_captura"), "csv")

    def test_reporte_locales_requires_selection(self):
        parse = get_spec("reporte_locales").parse
        with self.assertRaises(ValueError):
            parse({"establishment_ids": [], "department_id": ""})
        with self.assertRaises(ValueError):
            parse({"establishment_ids": [1], "include_fotos": False, "include_pdfs": False})
        run, key = parse({"establishment_ids": [3, "1", 3]})
        self.assertEqual(run["establishment_ids"], [1, 3])
        self.assertEqual(run, key)

    def test_aptot_locales_requires_establishment(self):
        with self.assertRaises(ValueError):
            get_spec("reporte_aptot_locales").parse({})


class ProgressWriterTests(unittest.TestCase):
    def _ctx(self):
        return SimpleNamespace(progress=mock.Mock())

    def test_counts_rows_and_reports_every_n_rows(self):
        ctx = self._ctx()
        buf = io.BytesIO()
        writer = runner._ProgressWriter(buf, ctx, total=12000, span=(5, 80), header_spaces=False)
        writer.write(b"a,b\n")
        for _ in range(12000):
            writer.write(b"1,2\n")
        writer.flush()
        self.assertEqual(writer.rows, 12000)
        # 5.000 y 10.000 filas
        self.assertEqual(ctx.progress.call_count, 2)
        pct = ctx.progress.call_args_list[-1].args[0]
        self.assertTrue(5 < pct <= 80)

    def test_header_spaces_across_chunks(self):
        buf = io.BytesIO()
        writer = runner._ProgressWriter(buf, self._ctx(), total=None, span=(5, 80), header_spaces=True)
        writer.write(b"hoj_num,fecha_")
        writer.write(b"margesi\nA_1,B_2\n")
        writer.flush()
        self.assertEqual(buf.getvalue(), b"hoj num,fecha margesi\nA_1,B_2\n", "solo la cabecera cambia")

    def test_accepts_text_chunks(self):
        buf = io.BytesIO()
        writer = runner._ProgressWriter(buf, self._ctx(), total=None, span=(5, 80), header_spaces=False)
        writer.write("ñ,á\n")
        self.assertEqual(buf.getvalue(), "ñ,á\n".encode())


def _row(state: str, *, created_min_ago: int, updated_min_ago: int | None = None, **kw):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        module="margesi",
        state=state,
        created_at=now - timedelta(minutes=created_min_ago),
        updated_at=now - timedelta(minutes=updated_min_ago if updated_min_ago is not None else created_min_ago),
        progress=kw.get("progress", 0),
        message=kw.get("message", ""),
        filename=kw.get("filename", "margesi.csv"),
        file_size_bytes=None,
        errors=[],
        created_by_id=kw.get("created_by_id"),
    )


class StaleTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(export_pending_timeout_minutes=30, export_stale_minutes=10)
        patcher = mock.patch.object(service, "get_settings", return_value=self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _alive(self, value):
        p = mock.patch.object(service.live, "is_alive", return_value=value)
        p.start()
        self.addCleanup(p.stop)

    def test_heartbeat_keeps_job_alive(self):
        self._alive(True)
        self.assertFalse(service.is_stale(_row("processing", created_min_ago=300)))

    def test_pending_too_long_without_worker(self):
        self._alive(False)
        self.assertTrue(service.is_stale(_row("pending", created_min_ago=31)))
        self.assertFalse(service.is_stale(_row("pending", created_min_ago=5)))

    def test_processing_without_recent_touch(self):
        self._alive(None)  # Redis caído: se decide por la base
        self.assertTrue(service.is_stale(_row("processing", created_min_ago=60, updated_min_ago=11)))
        self.assertFalse(service.is_stale(_row("processing", created_min_ago=60, updated_min_ago=2)))

    def test_finished_jobs_are_never_stale(self):
        self._alive(False)
        self.assertFalse(service.is_stale(_row("success", created_min_ago=999)))


class PayloadTests(unittest.TestCase):
    def test_live_progress_overlays_database(self):
        row = _row("processing", created_min_ago=1, progress=5, message="Generando CSV…")
        payload = service.job_payload(row, overlay={"state": "processing", "progress": "63", "message": "Generando 10 de 16"})
        self.assertEqual(payload["progress"], 63)
        self.assertEqual(payload["message"], "Generando 10 de 16")

    def test_final_database_state_wins_over_stale_redis(self):
        row = _row("success", created_min_ago=1, progress=100, message="Archivo listo", filename="x.xlsx")
        payload = service.job_payload(row, overlay={"state": "processing", "progress": "40", "message": "…"})
        self.assertEqual(payload["state"], "success")
        self.assertEqual(payload["progress"], 100)
        self.assertEqual(payload["format"], "xlsx")

    def test_started_by_me(self):
        uid = uuid.uuid4()
        row = _row("pending", created_min_ago=0, created_by_id=uid)
        self.assertTrue(service.job_payload(row, user_id=uid)["started_by_me"])
        self.assertFalse(service.job_payload(row, user_id=uuid.uuid4())["started_by_me"])


class CopyCompatTests(unittest.TestCase):
    """El COPY debe funcionar con psycopg2 (desarrollo) y psycopg 3 (producción)."""

    def test_psycopg2_cursor(self):
        from app.db import copy_compat

        cur = mock.Mock(spec=["mogrify", "copy_expert", "close"])
        cur.mogrify.return_value = b"COPY (SELECT 1) TO STDOUT"
        cur.copy_expert.side_effect = lambda sql, dest: dest.write(b"a\n1\n")
        conn = mock.Mock(cursor=mock.Mock(return_value=cur))
        self.assertEqual(copy_compat.render_sql(conn, "COPY (SELECT %s) TO STDOUT", (1,)), "COPY (SELECT 1) TO STDOUT")
        buf = io.BytesIO()
        copy_compat.copy_to(conn, "COPY (SELECT 1) TO STDOUT", buf)
        self.assertEqual(buf.getvalue(), b"a\n1\n")

    def test_psycopg3_cursor_without_mogrify_or_copy_expert(self):
        from app.db import copy_compat

        class Copy:
            def __enter__(self):
                return iter([memoryview(b"a\n"), memoryview(b"1\n")])

            def __exit__(self, *exc):
                return False

        cur = mock.Mock(spec=["copy", "close", "execute"])
        cur.copy.return_value = Copy()
        conn = mock.Mock(spec=["cursor", "driver_connection"], cursor=mock.Mock(return_value=cur))
        # psycopg 3 puede no estar instalado en desarrollo (sí en producción): se simula el módulo.
        client_cursor = mock.Mock()
        client_cursor.return_value.mogrify.return_value = "COPY (SELECT 1) TO STDOUT"
        fake_psycopg = SimpleNamespace(ClientCursor=client_cursor)
        with mock.patch.dict("sys.modules", {"psycopg": fake_psycopg}):
            self.assertEqual(copy_compat.render_sql(conn, "COPY (SELECT %s) TO STDOUT", (1,)), "COPY (SELECT 1) TO STDOUT")
            client_cursor.assert_called_once_with(conn.driver_connection)
        buf = io.BytesIO()
        copy_compat.copy_to(conn, "COPY (SELECT 1) TO STDOUT", buf)
        self.assertEqual(buf.getvalue(), b"a\n1\n")


class ItemPhotosZipTests(unittest.TestCase):
    """ZIP de fotos por local: nombres, partes y generación en streaming."""

    def test_entry_names_follow_slot_nomenclature(self):
        from app.modules.exports.item_photos import Photo

        base = "https://storage.googleapis.com/b/item-photos/t/x"
        self.assertEqual(Photo("12345", 1, base + ".jpg").entry_name, "12345-I.jpg")
        self.assertEqual(Photo("12345", 2, base + ".jpeg?v=1").entry_name, "12345-P.jpeg")
        self.assertEqual(Photo("12345", 3, base).entry_name, "12345-S.jpg")

    def test_parse_filters_key_ignores_part_labels(self):
        from app.modules.exports.item_photos import parse_filters

        run, key = parse_filters({"establishment_id": "7", "id_from": 1, "id_to": 50, "part": 2, "parts": 3})
        self.assertEqual(run["part"], 2)
        self.assertEqual(key, {"establishment_id": 7, "id_from": 1, "id_to": 50})
        with self.assertRaises(ValueError):
            parse_filters({})

    def test_plan_splits_without_breaking_items(self):
        from app.modules.exports import item_photos

        rows = [SimpleNamespace(id=i, foto1="a", foto2="b" if i % 2 else None, foto3=None) for i in range(1, 11)]
        db = mock.Mock()
        db.execute.return_value.all.return_value = rows
        with mock.patch.object(item_photos, "_establishment", return_value=SimpleNamespace(code="A01", description="SEDE")):
            plan = item_photos.build_plan(db, uuid.uuid4(), 1, part_max_photos=6)
        self.assertEqual(plan["photos"], 15)
        self.assertTrue(all(p["photos"] <= 6 for p in plan["parts"]))
        self.assertEqual(sum(p["items"] for p in plan["parts"]), 10)
        self.assertEqual([p["part"] for p in plan["parts"]], list(range(1, len(plan["parts"]) + 1)))
        # rangos contiguos y sin solaparse
        for a, b in zip(plan["parts"], plan["parts"][1:]):
            self.assertLess(a["id_to"], b["id_from"])

    def test_generate_writes_ordered_zip_and_missing_report(self):
        import tempfile
        import zipfile
        from pathlib import Path

        from app.modules.exports import item_photos
        from app.modules.exports.specs import StoredOutput

        photos = [
            item_photos.Photo("100", 1, "https://x/100_1.jpg"),
            item_photos.Photo("100", 2, "https://x/100_2.jpg"),
            item_photos.Photo("101", 1, "https://x/101_1.jpg"),
            item_photos.Photo("101", 3, "https://x/roto.jpg"),
        ]

        def fake_read(url, _tenant):
            return None if "roto" in url else (url.encode(), "image/jpeg")

        with tempfile.TemporaryDirectory() as tmp, mock.patch("tempfile.gettempdir", return_value=tmp), \
                mock.patch.object(item_photos, "_load_photos", return_value=(photos, "A01", "SEDE PRINCIPAL")), \
                mock.patch("app.core.item_photo_storage.read_item_photo_bytes", side_effect=fake_read), \
                mock.patch("app.core.export_storage.get_settings", return_value=SimpleNamespace(gcs_bucket="")):
            ctx = SimpleNamespace(job_id=uuid.uuid4(), progress=mock.Mock())
            out = item_photos.generate(ctx, uuid.uuid4(), {"establishment_id": 1, "part": 2, "parts": 3}, "zip")
            self.assertIsInstance(out, StoredOutput)
            self.assertIn("_parte2de3_", out.filename)
            path = Path(out.storage_path.removeprefix("local:"))
            self.assertEqual(path.stat().st_size, out.size)
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                self.assertEqual(
                    names,
                    [
                        "A01_SEDE_PRINCIPAL/100-I.jpg",
                        "A01_SEDE_PRINCIPAL/100-P.jpg",
                        "A01_SEDE_PRINCIPAL/101-I.jpg",
                        "A01_SEDE_PRINCIPAL/_fotos_no_disponibles.txt",
                    ],
                )
                self.assertEqual(zf.read("A01_SEDE_PRINCIPAL/100-P.jpg"), b"https://x/100_2.jpg")
                self.assertIn(b"101-S.jpg", zf.read("A01_SEDE_PRINCIPAL/_fotos_no_disponibles.txt"))
                self.assertIsNone(zf.testzip())


if __name__ == "__main__":
    unittest.main()
