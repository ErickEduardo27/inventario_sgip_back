from pydantic import BaseModel, Field

from app.modules.iam.schemas import UserComponentOut, UserOut


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class SessionOut(BaseModel):
    """Bootstrap de sesión: datos del usuario + componentes UI resueltos."""

    user: UserOut
    components: list[UserComponentOut]
