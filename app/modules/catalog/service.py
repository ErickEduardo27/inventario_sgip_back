from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.catalog.models import CatalogArea, CatalogPosition, CatalogSite


class CatalogService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_sites(self, tenant_id: UUID) -> list[CatalogSite]:
        stmt = (
            select(CatalogSite)
            .where(CatalogSite.tenant_id == tenant_id, CatalogSite.is_deleted.is_(False))
            .order_by(CatalogSite.name)
        )
        return list(self.db.scalars(stmt).all())

    def list_areas(self, tenant_id: UUID) -> list[CatalogArea]:
        stmt = (
            select(CatalogArea)
            .where(CatalogArea.tenant_id == tenant_id, CatalogArea.is_deleted.is_(False))
            .order_by(CatalogArea.name)
        )
        return list(self.db.scalars(stmt).all())

    def list_positions(self, tenant_id: UUID) -> list[CatalogPosition]:
        stmt = (
            select(CatalogPosition)
            .where(CatalogPosition.tenant_id == tenant_id, CatalogPosition.is_deleted.is_(False))
            .order_by(CatalogPosition.name)
        )
        return list(self.db.scalars(stmt).all())

    def create_site(self, tenant_id: UUID, name: str) -> CatalogSite:
        row = CatalogSite(tenant_id=tenant_id, name=name.strip())
        self.db.add(row)
        try:
            self.db.commit()
            self.db.refresh(row)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_catalog_sites_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe una sede con ese nombre", 409) from e
            raise AppError("No se pudo crear la sede", 400) from e
        return row

    def update_site(self, tenant_id: UUID, site_id: UUID, name: str) -> CatalogSite:
        s = self.db.scalar(
            select(CatalogSite).where(
                CatalogSite.id == site_id,
                CatalogSite.tenant_id == tenant_id,
                CatalogSite.is_deleted.is_(False),
            )
        )
        if not s:
            raise AppError("Sede no encontrada", 404)
        s.name = name.strip()
        try:
            self.db.commit()
            self.db.refresh(s)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_catalog_sites_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe una sede con ese nombre", 409) from e
            raise AppError("No se pudo actualizar la sede", 400) from e
        return s

    def delete_site(self, tenant_id: UUID, site_id: UUID) -> None:
        s = self.db.scalar(
            select(CatalogSite).where(
                CatalogSite.id == site_id,
                CatalogSite.tenant_id == tenant_id,
                CatalogSite.is_deleted.is_(False),
            )
        )
        if not s:
            raise AppError("Sede no encontrada", 404)
        s.is_deleted = True
        self.db.commit()

    def create_area(self, tenant_id: UUID, name: str) -> CatalogArea:
        row = CatalogArea(tenant_id=tenant_id, name=name.strip())
        self.db.add(row)
        try:
            self.db.commit()
            self.db.refresh(row)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_catalog_areas_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe un área con ese nombre", 409) from e
            raise AppError("No se pudo crear el área", 400) from e
        return row

    def update_area(self, tenant_id: UUID, area_id: UUID, name: str) -> CatalogArea:
        a = self.db.scalar(
            select(CatalogArea).where(
                CatalogArea.id == area_id,
                CatalogArea.tenant_id == tenant_id,
                CatalogArea.is_deleted.is_(False),
            )
        )
        if not a:
            raise AppError("Área no encontrada", 404)
        a.name = name.strip()
        try:
            self.db.commit()
            self.db.refresh(a)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_catalog_areas_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe un área con ese nombre", 409) from e
            raise AppError("No se pudo actualizar el área", 400) from e
        return a

    def delete_area(self, tenant_id: UUID, area_id: UUID) -> None:
        a = self.db.scalar(
            select(CatalogArea).where(
                CatalogArea.id == area_id,
                CatalogArea.tenant_id == tenant_id,
                CatalogArea.is_deleted.is_(False),
            )
        )
        if not a:
            raise AppError("Área no encontrada", 404)
        a.is_deleted = True
        self.db.commit()

    def create_position(self, tenant_id: UUID, name: str) -> CatalogPosition:
        row = CatalogPosition(tenant_id=tenant_id, name=name.strip())
        self.db.add(row)
        try:
            self.db.commit()
            self.db.refresh(row)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_catalog_positions_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe un cargo con ese nombre", 409) from e
            raise AppError("No se pudo crear el cargo", 400) from e
        return row

    def update_position(self, tenant_id: UUID, position_id: UUID, name: str) -> CatalogPosition:
        p = self.db.scalar(
            select(CatalogPosition).where(
                CatalogPosition.id == position_id,
                CatalogPosition.tenant_id == tenant_id,
                CatalogPosition.is_deleted.is_(False),
            )
        )
        if not p:
            raise AppError("Cargo no encontrado", 404)
        p.name = name.strip()
        try:
            self.db.commit()
            self.db.refresh(p)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_catalog_positions_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe un cargo con ese nombre", 409) from e
            raise AppError("No se pudo actualizar el cargo", 400) from e
        return p

    def delete_position(self, tenant_id: UUID, position_id: UUID) -> None:
        p = self.db.scalar(
            select(CatalogPosition).where(
                CatalogPosition.id == position_id,
                CatalogPosition.tenant_id == tenant_id,
                CatalogPosition.is_deleted.is_(False),
            )
        )
        if not p:
            raise AppError("Cargo no encontrado", 404)
        p.is_deleted = True
        self.db.commit()
