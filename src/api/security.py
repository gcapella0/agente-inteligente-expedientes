from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from datetime import timezone
from passlib.context import CryptContext

from src.core.logger import get_agent_logger

logger = get_agent_logger("api")

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "cambiar-en-produccion-clave-larga-y-compleja-12345!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 horas

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hashea una contraseña con bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash bcrypt."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str,
    rol: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Crea un JWT token firmado con HS256."""
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "rol": rol,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"Token creado para: {subject}, rol: {rol}")
    return token


def decode_token(token: str) -> dict:
    """Decodifica y valida un JWT token. Lanza ValueError si es inválido."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("Token expirado")
        raise ValueError("Token expirado")
    except jwt.InvalidTokenError:
        logger.warning("Token inválido")
        raise ValueError("Token inválido")


def hash_sha256(text: str) -> str:
    """Hash SHA-256 de un texto."""
    return hashlib.sha256(text.encode()).hexdigest()
