from fastapi import APIRouter

from app.api.tenant_context_router import router as tenant_context_router
from app.modules.auth.router import router as auth_router
from app.modules.iam.router import router as iam_router
from app.modules.inventory.public_router import router as inventory_public_router
from app.modules.inventory.router import router as inventory_router
from app.modules.settings.router import router as settings_router
from app.modules.templates.public_router import router as templates_public_router
from app.modules.tenants.router import router as tenants_router

api_router = APIRouter(prefix="/api")
api_router.include_router(tenant_context_router, prefix="/tenant", tags=["tenant"])
api_router.include_router(tenants_router, prefix="/tenants", tags=["tenants"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(iam_router, prefix="/iam", tags=["iam"])
api_router.include_router(templates_public_router, prefix="/public", tags=["public"])
api_router.include_router(inventory_public_router, prefix="/public", tags=["public"])
api_router.include_router(inventory_router, tags=["inventory"])
api_router.include_router(settings_router, prefix="/settings", tags=["settings"])
