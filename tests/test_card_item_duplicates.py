"""Reglas de unicidad al registrar bienes en una hoja (sin base de datos).

    venv/Scripts/python.exe -m unittest tests.test_card_item_duplicates -v
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from app.modules.inventory import models as m
from app.modules.inventory import service as inv
from app.modules.inventory.schemas import CardItemWrite

TENANT = uuid.uuid4()
OWNER = {"item_id": 7, "inv_num": "00000120", "hoj_num": "000015", "ambiente": "Oficina 2"}


def _body(**kw) -> CardItemWrite:
    base = dict(
        inv_num=120,
        mar_des="Silla",
        mar_col="Negro",
        mar_mar="SM",
        mar_mod="SM",
        mar_ser="SS",
        mar_med="SM",
        no_conciliar=True,
    )
    base.update(kw)
    return CardItemWrite(**base)


def _db(marg=None):
    card = SimpleNamespace(id=5, tenant_id=TENANT, state=1, hoj_num=15, hoj_can_tot=0)

    def get(model, _id):
        if model is m.InvCard:
            return card
        if model is m.InvMargesiItem:
            return marg
        return None

    db = mock.MagicMock()
    db.get.side_effect = get
    return db


class StrictInvNumTests(unittest.TestCase):
    def test_strict_rejects_used_number_with_detail(self):
        with (
            mock.patch.object(inv, "_inv_num_in_use", return_value=True),
            mock.patch.object(inv, "_item_card_owner_detail", return_value=OWNER),
            mock.patch.object(inv, "_next_available_inv_num", return_value=121),
        ):
            res = inv.store_card_item(_db(), TENANT, 5, _body(strict_inv_num=True))
        self.assertFalse(res.ok)
        self.assertEqual(res.conflict["code"], "inv_num_duplicado")
        self.assertEqual(res.conflict["existing"], OWNER)
        self.assertEqual(res.conflict["suggested_inv_num"], inv.format_inv_num(121))
        self.assertIn("000015", res.message)

    def test_non_strict_keeps_reassigning(self):
        db = _db()
        with (
            mock.patch.object(inv, "_next_available_inv_num", return_value=121) as nxt,
            mock.patch.object(inv, "_item_card_owner_detail") as owner,
        ):
            db.commit.side_effect = RuntimeError("stop after insert")
            with self.assertRaises(RuntimeError):
                inv.store_card_item(db, TENANT, 5, _body())
        nxt.assert_called_once()
        owner.assert_not_called()


class MargesiConflictTests(unittest.TestCase):
    def test_margesi_already_linked_is_rejected(self):
        marg = SimpleNamespace(id=99, tenant_id=TENANT, inv_sit="C", mar_cpat="1", mar_des="Silla")
        with (
            mock.patch.object(inv, "_inv_num_in_use", return_value=False),
            mock.patch.object(inv, "_item_card_owner_detail", return_value=OWNER) as owner,
        ):
            res = inv.store_card_item(
                _db(marg), TENANT, 5, _body(no_conciliar=False, id_margesi=99, strict_inv_num=True)
            )
        self.assertFalse(res.ok)
        self.assertEqual(res.conflict["code"], "margesi_ya_conciliado")
        owner.assert_called_with(mock.ANY, TENANT, id_margesi=99, exclude_id=None)


class ItemWritePermissionTests(unittest.TestCase):
    """``hoja_captura``: alta exige ``create`` y edición ``edit`` (como la web)."""

    user = SimpleNamespace(id=uuid.uuid4())

    def _check(self, body: CardItemWrite, perms: set[str], registered_by_user: bool = False):
        from fastapi import HTTPException

        from app.modules.inventory import router

        def has(_user, _db, _tenant, code, action):
            return code == "hoja_captura" and action in perms

        with (
            mock.patch.object(router, "has_permission", side_effect=has),
            mock.patch.object(inv, "item_registered_by_in_open_card", return_value=registered_by_user),
        ):
            try:
                router._require_item_write(mock.MagicMock(), TENANT, self.user, body)
            except HTTPException as exc:
                return exc.status_code
        return None

    def test_create_requires_create(self):
        self.assertEqual(self._check(_body(), {"view", "edit"}), 403)
        self.assertIsNone(self._check(_body(), {"create"}))

    def test_edit_requires_edit(self):
        self.assertEqual(self._check(_body(id=5), {"view", "create"}), 403)
        self.assertIsNone(self._check(_body(id=5), {"edit"}))

    def test_creator_can_complete_own_item(self):
        # La app adjunta las fotos con una edición justo después del alta.
        self.assertIsNone(self._check(_body(id=5), {"create"}, registered_by_user=True))
        self.assertEqual(self._check(_body(id=5), {"view"}, registered_by_user=True), 403)


def _route_guards(path: str, method: str) -> list[tuple]:
    """(códigos, acción) de los ``require_permission`` / ``require_any_permission`` de una ruta."""
    from app.modules.inventory import router

    route = next(r for r in router.router.routes if r.path.endswith(path) and method in r.methods)
    guards = []
    for dep in route.dependant.dependencies:
        cells = dict(zip(dep.call.__code__.co_freevars, (c.cell_contents for c in dep.call.__closure__ or ())))
        if "action" in cells:
            codes = cells.get("codes") or (cells.get("code"),)
            guards.append((tuple(codes), cells["action"]))
    return guards


class ItemRoutePermissionTests(unittest.TestCase):
    def test_move_and_translate_require_edit(self):
        for path in ("/hoja-captura/move/{item_id}", "/item-cards/{item_id}/translate"):
            self.assertIn((("hoja_captura",), "edit"), _route_guards(path, "POST"), path)

    def test_delete_requires_delete_in_hoja_or_bienes(self):
        self.assertIn(
            (("hoja_captura", "bienes"), "delete"),
            _route_guards("/item-cards/{item_id}", "DELETE"),
        )

    def test_import_requires_create(self):
        self.assertIn((("hoja_captura",), "create"), _route_guards("/hoja-captura/import", "POST"))


if __name__ == "__main__":
    unittest.main()
