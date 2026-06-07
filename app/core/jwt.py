from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt

from app.core.config import get_settings


class TokenError(Exception):
    """Error al decodificar o validar un JWT."""


def encode_access_token(user_id: UUID, tenant_id: UUID, extra: dict[str, Any] | None = None) -> tuple[str, int]:
    """Firma un access token. Devuelve `(token, expires_in_seconds)`."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_expires_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.jwt_expires_minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("Sesión expirada") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("Token inválido") from e
    if payload.get("type") != "access":
        raise TokenError("Tipo de token inválido")
    return payload
