from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.tenants.schemas import TenantPublicOut
from app.modules.tenants.service import TenantService

router = APIRouter()


@router.get("/by-slug/{slug}", response_model=TenantPublicOut)
def get_tenant_by_slug(slug: str, db: Session = Depends(get_db)):
    """Resolución pública por slug (subdominio / marca). Sin cabecera de tenant."""
    try:
        t = TenantService(db).get_public_by_slug(slug)
        return TenantPublicOut.model_validate(t)
    except AppError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
