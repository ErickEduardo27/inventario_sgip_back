from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.catalog.models import CatalogArea, CatalogPosition, CatalogSite
from app.modules.contacts.models import Contact
from app.modules.contacts.schemas import ContactCreate, ContactOut, ContactSummary, ContactUpdate


class ContactService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _normalize_number(self, number: str) -> str:
        return number.strip().replace(" ", "")

    def _ensure_catalog(
        self,
        tenant_id: UUID,
        *,
        site_id: UUID | None,
        area_id: UUID | None,
        position_id: UUID | None,
    ) -> None:
        if site_id is not None:
            ok = self.db.scalar(
                select(CatalogSite.id).where(
                    CatalogSite.id == site_id,
                    CatalogSite.tenant_id == tenant_id,
                    CatalogSite.is_deleted.is_(False),
                )
            )
            if not ok:
                raise AppError("La sede seleccionada no es válida", 400)
        if area_id is not None:
            ok = self.db.scalar(
                select(CatalogArea.id).where(
                    CatalogArea.id == area_id,
                    CatalogArea.tenant_id == tenant_id,
                    CatalogArea.is_deleted.is_(False),
                )
            )
            if not ok:
                raise AppError("El área seleccionada no es válida", 400)
        if position_id is not None:
            ok = self.db.scalar(
                select(CatalogPosition.id).where(
                    CatalogPosition.id == position_id,
                    CatalogPosition.tenant_id == tenant_id,
                    CatalogPosition.is_deleted.is_(False),
                )
            )
            if not ok:
                raise AppError("El cargo seleccionado no es válido", 400)

    def _name_maps(self, tenant_id: UUID, contacts: list[Contact]) -> tuple[dict[UUID, str], dict[UUID, str], dict[UUID, str]]:
        site_ids = {c.site_id for c in contacts if c.site_id}
        area_ids = {c.area_id for c in contacts if c.area_id}
        pos_ids = {c.position_id for c in contacts if c.position_id}

        sites_m: dict[UUID, str] = {}
        areas_m: dict[UUID, str] = {}
        pos_m: dict[UUID, str] = {}

        if site_ids:
            rows = self.db.execute(
                select(CatalogSite.id, CatalogSite.name).where(
                    CatalogSite.tenant_id == tenant_id,
                    CatalogSite.id.in_(site_ids),
                    CatalogSite.is_deleted.is_(False),
                )
            ).all()
            sites_m = {r[0]: r[1] for r in rows}
        if area_ids:
            rows = self.db.execute(
                select(CatalogArea.id, CatalogArea.name).where(
                    CatalogArea.tenant_id == tenant_id,
                    CatalogArea.id.in_(area_ids),
                    CatalogArea.is_deleted.is_(False),
                )
            ).all()
            areas_m = {r[0]: r[1] for r in rows}
        if pos_ids:
            rows = self.db.execute(
                select(CatalogPosition.id, CatalogPosition.name).where(
                    CatalogPosition.tenant_id == tenant_id,
                    CatalogPosition.id.in_(pos_ids),
                    CatalogPosition.is_deleted.is_(False),
                )
            ).all()
            pos_m = {r[0]: r[1] for r in rows}

        return sites_m, areas_m, pos_m

    def _to_out(self, c: Contact, sites_m: dict[UUID, str], areas_m: dict[UUID, str], pos_m: dict[UUID, str]) -> ContactOut:
        return ContactOut(
            id=c.id,
            tenant_id=c.tenant_id,
            created_at=c.created_at,
            first_name=c.first_name,
            last_name=c.last_name,
            whatsapp_number=c.whatsapp_number,
            email=c.email,
            document=c.document,
            site_id=c.site_id,
            area_id=c.area_id,
            position_id=c.position_id,
            region=c.region,
            status=c.status,
            note=c.note,
            site_name=sites_m.get(c.site_id) if c.site_id else None,
            area_name=areas_m.get(c.area_id) if c.area_id else None,
            position_name=pos_m.get(c.position_id) if c.position_id else None,
        )

    def list_contacts(
        self,
        tenant_id: UUID,
        *,
        search: str | None = None,
        site_id: UUID | None = None,
        area_id: UUID | None = None,
        position_id: UUID | None = None,
        region: str | None = None,
        status: str | None = None,
    ) -> list[ContactOut]:
        stmt = select(Contact).where(Contact.tenant_id == tenant_id, Contact.is_deleted.is_(False))
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Contact.first_name).like(term),
                    func.lower(Contact.last_name).like(term),
                    func.lower(Contact.whatsapp_number).like(term),
                    func.lower(func.coalesce(Contact.document, "")).like(term),
                    func.lower(func.coalesce(Contact.email, "")).like(term),
                )
            )
        if site_id:
            stmt = stmt.where(Contact.site_id == site_id)
        if area_id:
            stmt = stmt.where(Contact.area_id == area_id)
        if position_id:
            stmt = stmt.where(Contact.position_id == position_id)
        if region:
            stmt = stmt.where(Contact.region == region)
        if status:
            stmt = stmt.where(Contact.status == status)
        stmt = stmt.order_by(Contact.first_name, Contact.last_name)
        contacts = list(self.db.scalars(stmt).all())
        sm, am, pm = self._name_maps(tenant_id, contacts)
        return [self._to_out(c, sm, am, pm) for c in contacts]

    def get_contact(self, tenant_id: UUID, contact_id: UUID) -> Contact:
        c = self.db.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.tenant_id == tenant_id,
                Contact.is_deleted.is_(False),
            )
        )
        if not c:
            raise AppError("Contacto no encontrado", 404)
        return c

    def get_contact_out(self, tenant_id: UUID, contact_id: UUID) -> ContactOut:
        c = self.get_contact(tenant_id, contact_id)
        sm, am, pm = self._name_maps(tenant_id, [c])
        return self._to_out(c, sm, am, pm)

    def create_contact(self, tenant_id: UUID, body: ContactCreate) -> ContactOut:
        self._ensure_catalog(
            tenant_id,
            site_id=body.site_id,
            area_id=body.area_id,
            position_id=body.position_id,
        )
        c = Contact(
            tenant_id=tenant_id,
            first_name=body.first_name.strip(),
            last_name=(body.last_name or "").strip(),
            whatsapp_number=self._normalize_number(body.whatsapp_number),
            email=body.email,
            document=(body.document or None) and body.document.strip(),
            site_id=body.site_id,
            area_id=body.area_id,
            position_id=body.position_id,
            region=(body.region or None) and body.region.strip(),
            status=body.status,
            note=(body.note or None) and body.note.strip(),
        )
        self.db.add(c)
        try:
            self.db.commit()
            self.db.refresh(c)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_contacts_tenant_whatsapp" in str(e.orig).lower():
                raise AppError("Ya existe un contacto con ese número de WhatsApp", 409) from e
            raise AppError("No se pudo crear el contacto", 400) from e
        return self.get_contact_out(tenant_id, c.id)

    def update_contact(self, tenant_id: UUID, contact_id: UUID, body: ContactUpdate) -> ContactOut:
        c = self.get_contact(tenant_id, contact_id)
        data = body.model_dump(exclude_unset=True)
        if "whatsapp_number" in data and data["whatsapp_number"]:
            data["whatsapp_number"] = self._normalize_number(data["whatsapp_number"])
        next_site = data.get("site_id", c.site_id)
        next_area = data.get("area_id", c.area_id)
        next_pos = data.get("position_id", c.position_id)
        if "site_id" in data or "area_id" in data or "position_id" in data:
            self._ensure_catalog(
                tenant_id,
                site_id=next_site,
                area_id=next_area,
                position_id=next_pos,
            )
        for k, v in data.items():
            setattr(c, k, v)
        try:
            self.db.commit()
            self.db.refresh(c)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_contacts_tenant_whatsapp" in str(e.orig).lower():
                raise AppError("Ya existe un contacto con ese número de WhatsApp", 409) from e
            raise AppError("No se pudo actualizar el contacto", 400) from e
        return self.get_contact_out(tenant_id, c.id)

    def delete_contact(self, tenant_id: UUID, contact_id: UUID) -> None:
        c = self.get_contact(tenant_id, contact_id)
        c.is_deleted = True
        self.db.commit()

    def summary(self, tenant_id: UUID) -> ContactSummary:
        rows = self.db.execute(
            select(Contact.status, func.count(Contact.id))
            .where(Contact.tenant_id == tenant_id, Contact.is_deleted.is_(False))
            .group_by(Contact.status)
        ).all()
        counts: dict[str, int] = {row[0]: row[1] for row in rows}
        return ContactSummary(
            total=sum(counts.values()),
            activos=counts.get("activo", 0),
            inactivos=counts.get("inactivo", 0),
            observados=counts.get("observado", 0),
            invalidos=counts.get("numero_invalido", 0),
        )
