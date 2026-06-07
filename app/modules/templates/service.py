import re
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.templates.header_image import decode_template_header_upload
from app.modules.templates.meta_graph import (
    body_to_meta_body_and_example,
    create_waba_message_template,
    list_waba_message_templates,
    slugify_meta_template_name,
)
from app.modules.templates.models import MessageTemplate
from app.modules.templates.schemas import (
    MetaWabaTemplateRow,
    TemplateCreate,
    TemplateUpdate,
)

VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def extract_variables(body: str) -> list[str]:
    """Extrae nombres únicos de variables usadas en el cuerpo, en orden."""
    seen: list[str] = []
    for match in VARIABLE_PATTERN.finditer(body or ""):
        v = match.group(1)
        if v not in seen:
            seen.append(v)
    return seen


class TemplateService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_templates(self, tenant_id: UUID) -> list[MessageTemplate]:
        return list(
            self.db.scalars(
                select(MessageTemplate)
                .where(MessageTemplate.tenant_id == tenant_id, MessageTemplate.is_deleted.is_(False))
                .order_by(MessageTemplate.created_at.desc())
            ).all()
        )

    def get_template(self, tenant_id: UUID, template_id: UUID) -> MessageTemplate:
        t = self.db.scalar(
            select(MessageTemplate).where(
                MessageTemplate.id == template_id,
                MessageTemplate.tenant_id == tenant_id,
                MessageTemplate.is_deleted.is_(False),
            )
        )
        if not t:
            raise AppError("Plantilla no encontrada", 404)
        return t

    def create_template(self, tenant_id: UUID, body: TemplateCreate) -> MessageTemplate:
        variables = body.variables or extract_variables(body.body)
        meta_cat = body.wa_meta_category
        meta_lang = body.wa_language
        hdr_fmt = (body.wa_header_format or "NONE").strip().upper()
        settings = get_settings()

        img_blob: bytes | None = None
        img_mime: str | None = None
        img_token: UUID | None = None

        if hdr_fmt == "IMAGE":
            pub = settings.public_api_base_url.strip()
            if not pub.startswith("https://"):
                raise AppError(
                    "Para plantillas con imagen define PUBLIC_API_BASE_URL en el servidor (URL HTTPS pública del API, "
                    "sin barra final). Meta descargará la imagen desde "
                    f"{pub or '(vacío)'}/api/public/template-header-image/<token>.",
                    400,
                )
            b64 = (body.wa_header_image_base64 or "").strip()
            if not b64:
                raise AppError(
                    "Adjunta una imagen de cabecera (JPEG, PNG o WebP, máx. 2 MB). Se guardará en la base de datos.",
                    400,
                )
            img_blob, img_mime = decode_template_header_upload(b64, body.wa_header_image_mime)
            img_token = uuid.uuid4()

        t = MessageTemplate(
            tenant_id=tenant_id,
            name=body.name.strip(),
            category=body.category,
            body=body.body,
            variables=variables,
            status=body.status,
            wa_header_format="IMAGE" if hdr_fmt == "IMAGE" else None,
            wa_quick_reply_buttons=body.wa_quick_reply_buttons[:] if body.wa_quick_reply_buttons else None,
            wa_header_image_blob=img_blob,
            wa_header_image_mime=img_mime,
            wa_header_image_token=img_token,
        )
        self.db.add(t)
        try:
            self.db.flush()
        except IntegrityError as e:
            self.db.rollback()
            if "uq_templates_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe una plantilla con ese nombre", 409) from e
            raise AppError("No se pudo crear la plantilla", 400) from e

        try:
            self._push_row_to_meta(t, meta_category=meta_cat, language=meta_lang)
            self.db.commit()
            self.db.refresh(t)
        except AppError:
            self.db.rollback()
            raise
        except IntegrityError as e:
            self.db.rollback()
            if "uq_templates_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe una plantilla con ese nombre", 409) from e
            raise AppError("No se pudo crear la plantilla", 400) from e
        return t

    def _push_row_to_meta(
        self,
        t: MessageTemplate,
        *,
        meta_category: str,
        language: str,
    ) -> None:
        settings = get_settings()
        meta_name = slugify_meta_template_name(t.name)
        meta_text, samples = body_to_meta_body_and_example(t.body)
        if len(meta_text) > 1024:
            raise AppError("El cuerpo para Meta supera 1024 caracteres (límite del BODY).", 400)

        hdr = "IMAGE" if (t.wa_header_format or "").strip().upper() == "IMAGE" else None
        qrs = list(t.wa_quick_reply_buttons or [])
        resp, lang_norm = create_waba_message_template(
            settings,
            meta_name=meta_name,
            language=language.strip(),
            category=meta_category.strip(),
            body_text=meta_text,
            example_row=samples,
            header_format=hdr,
            quick_reply_buttons=qrs,
        )
        api_status = str(resp.get("status") or "PENDING").strip().upper()
        tid = str(resp.get("id") or "").strip()[:128] or None

        t.wa_meta_name = meta_name
        t.wa_language = lang_norm
        t.wa_meta_category = meta_category.strip().upper()
        t.wa_review_status = api_status
        t.wa_review_reason = None
        t.wa_submitted_at = datetime.now(timezone.utc)
        t.wa_graph_template_id = tid

    def update_template(self, tenant_id: UUID, template_id: UUID, body: TemplateUpdate) -> MessageTemplate:
        t = self.get_template(tenant_id, template_id)
        data = body.model_dump(exclude_unset=True)
        if "body" in data and data["body"] is not None and "variables" not in data:
            data["variables"] = extract_variables(data["body"])
        for k, v in data.items():
            setattr(t, k, v)
        try:
            self.db.commit()
            self.db.refresh(t)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_templates_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe una plantilla con ese nombre", 409) from e
            raise AppError("No se pudo actualizar la plantilla", 400) from e
        return t

    def delete_template(self, tenant_id: UUID, template_id: UUID) -> None:
        t = self.get_template(tenant_id, template_id)
        t.is_deleted = True
        self.db.commit()

    def submit_to_meta(
        self,
        tenant_id: UUID,
        template_id: UUID,
        *,
        meta_category: str,
        language: str,
    ) -> MessageTemplate:
        t = self.get_template(tenant_id, template_id)
        st = (t.wa_review_status or "").strip().upper()
        if st == "PENDING":
            raise AppError("Esta plantilla ya está en revisión en Meta.", 409)
        if st == "APPROVED":
            raise AppError(
                "Esta plantilla ya fue aprobada por Meta. Para otra versión, crea una plantilla nueva "
                "con otro nombre (el nombre en Meta debe ser único).",
                409,
            )

        try:
            self._push_row_to_meta(t, meta_category=meta_category, language=language)
            self.db.commit()
            self.db.refresh(t)
        except AppError:
            self.db.rollback()
            raise
        return t

    def list_meta_waba_templates(self) -> list[MetaWabaTemplateRow]:
        rows = list_waba_message_templates(get_settings())
        parsed = [MetaWabaTemplateRow.from_graph(x) for x in rows]
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

        def _ts(r: MetaWabaTemplateRow) -> datetime:
            t = r.last_updated_time
            if t is None:
                return epoch
            if t.tzinfo is None:
                return t.replace(tzinfo=timezone.utc)
            return t

        parsed.sort(key=lambda r: (_ts(r), (r.name or "").lower(), (r.language or "").lower()), reverse=True)
        return parsed
