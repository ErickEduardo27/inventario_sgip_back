from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.jwt import encode_access_token
from app.core.security import hash_password, verify_password
from app.modules.auth.schemas import LoginRequest, LoginResponse, ProfileUpdate
from app.modules.iam.models import User
from app.modules.iam.schemas import UserOut
from app.shared.utils.strings import normalize_email


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def login(self, tenant_id: UUID, body: LoginRequest) -> LoginResponse:
        email = normalize_email(body.email)
        user = self.db.scalar(
            select(User).where(
                User.tenant_id == tenant_id,
                User.email == email,
                User.is_deleted.is_(False),
            )
        )
        if not user or not verify_password(body.password, user.password_hash):
            raise AppError("Credenciales inválidas", 401)
        if user.status != "active":
            raise AppError("Usuario no activo", 403)

        user.last_access_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)

        token, expires_in = encode_access_token(user.id, tenant_id)
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            user=UserOut.model_validate(user),
        )

    def update_own_profile(self, user: User, body: ProfileUpdate) -> User:
        if not body.model_fields_set:
            raise AppError("No hay cambios para guardar", 400)

        if body.full_name is not None:
            user.full_name = body.full_name.strip()

        if body.new_password:
            if not verify_password(body.current_password or "", user.password_hash):
                raise AppError("La contraseña actual no es correcta", 400)
            user.password_hash = hash_password(body.new_password)

        try:
            self.db.commit()
            self.db.refresh(user)
        except Exception as e:
            self.db.rollback()
            raise AppError("No se pudo actualizar el perfil", 400) from e
        return user
