from pydantic import BaseModel, Field, model_validator

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


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    current_password: str | None = Field(default=None, min_length=1, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_password_change(self) -> "ProfileUpdate":
        if self.new_password and not self.current_password:
            raise ValueError("Indique la contraseña actual para cambiarla")
        if self.current_password and not self.new_password:
            raise ValueError("Indique la nueva contraseña")
        return self
