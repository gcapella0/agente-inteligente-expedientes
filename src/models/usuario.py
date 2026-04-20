from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class UsuarioModel(BaseModel):
    """Modelo de usuario en MongoDB."""

    email: EmailStr
    password_hash: str
    nombre_completo: str
    rol: Literal["admin", "usuario", "sistema"] = "usuario"
    activo: bool = True
    ultimo_login: Optional[datetime] = None
    creado_en: datetime = Field(default_factory=datetime.now)
    actualizado_en: datetime = Field(default_factory=datetime.now)


class UsuarioResponse(BaseModel):
    """Datos públicos de usuario (sin contraseña)."""

    email: str
    nombre_completo: str
    rol: str
    activo: bool


class LoginRequest(BaseModel):
    """Credenciales de login."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """Respuesta del endpoint de login."""

    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioResponse


class UsuarioCreate(BaseModel):
    """Datos para crear un nuevo usuario (solo admin)."""

    email: str
    password: str
    nombre_completo: str
    rol: Literal["admin", "usuario", "sistema"] = "usuario"
