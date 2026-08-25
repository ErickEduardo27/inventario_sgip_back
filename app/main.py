import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.iam.models import Role, User, user_roles
from app.modules.tenants.models import Tenant


def _cors_allow_origins() -> list[str]:
    """Orígenes CORS: desarrollo local, `FRONTEND_URL`, `CORS_EXTRA_ORIGINS` y hosts fijos de producción."""
    settings = get_settings()
    defaults = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "https://inventario-sgip.onrender.com",
        "https://www.inventario-sgip.onrender.com",
        "https://inventarioqa.redbaron.click",
        "https://www.inventarioqa.redbaron.click",
    ]
    if settings.frontend_url.strip():
        defaults.append(settings.frontend_url.strip().rstrip("/"))
    extra = [x.strip().rstrip("/") for x in settings.cors_extra_origins.split(",") if x.strip()]
    return list(dict.fromkeys(defaults + extra))


def _cors_allow_origin_regex() -> str:
    """Regex de orígenes permitidos (subdominios localhost, Render, Cloud Run, etc.)."""
    return (
        r"https?://([a-zA-Z0-9-]+\.)+localhost(:\d+)?"
        r"|https?://localhost(:\d+)?"
        r"|https?://127\.0\.0\.1(:\d+)?"
        r"|https://[\w-]+(\.[\w-]+)*\.onrender\.com"
        r"|https://[\w-]+(\.[\w-]+)*\.run\.app"
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    with SessionLocal() as db:
        if not db.scalar(select(Tenant).where(Tenant.slug == settings.default_tenant_slug)):
            db.add(
                Tenant(
                    name="Inventario SGIP",
                    slug=settings.default_tenant_slug,
                    status="active",
                    plan_code="enterprise",
                    timezone="America/Lima",
                    locale="es-PE",
                    currency="PEN",
                )
            )
            db.commit()
        if settings.seed_demo_user_requested:
            t = db.scalar(select(Tenant).where(Tenant.slug == settings.default_tenant_slug))
            if t and not db.scalar(
                select(User).where(User.tenant_id == t.id, User.is_deleted.is_(False)).limit(1)
            ):
                pwd = os.getenv("DEMO_IAM_PASSWORD", "demo12345")
                admin_role = db.scalar(
                    select(Role).where(Role.code == "administrador", Role.tenant_id.is_(None))
                )
                user = User(
                    tenant_id=t.id,
                    full_name="Administrador",
                    email="admin@local.test",
                    password_hash=hash_password(pwd),
                    status="active",
                    is_superadmin=True,
                )
                db.add(user)
                db.flush()
                if admin_role:
                    db.execute(
                        user_roles.insert().values(user_id=user.id, role_id=admin_role.id)
                    )
                db.commit()
    yield


app = FastAPI(title="Inventario SGIP API", lifespan=lifespan)
# Cloud Run termina TLS y reenvía HTTP al contenedor; sin esto los 307 de FastAPI
# salen como Location: http://... y el navegador los bloquea (mixed-content).
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_origin_regex=_cors_allow_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"message": "Inventario SGIP API"}


@app.get("/health")
def health():
    return {"status": "ok"}
