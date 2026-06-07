import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.router import api_router
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.iam.models import Role, User, user_roles
from app.modules.tenants.models import Tenant


def _cors_allow_origins() -> list[str]:
    """Orígenes CORS: Vite (5173), preview (4173) y `CORS_EXTRA_ORIGINS` en .env (IP de red, otro host)."""
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
        "https://mi-backend-238356790822.us-central1.run.app",
        "https://inventario-sgip.onrender.com",
    ]
    extra = [x.strip() for x in settings.cors_extra_origins.split(",") if x.strip()]
    return list(dict.fromkeys(defaults + extra))


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_origin_regex=r"https?://([a-zA-Z0-9-]+\.)+localhost(:\d+)?|https?://localhost(:\d+)?|https?://127\.0\.0\.1(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"message": "Inventario SGIP API"}


@app.get("/health")
def health():
    return {"status": "ok"}
