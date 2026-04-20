from __future__ import annotations

from fastapi import Header, HTTPException, status

from src.api.security import decode_token
from src.core.logger import get_agent_logger

logger = get_agent_logger("api")


async def verify_token(authorization: str = Header(...)) -> dict:
    """Verifica y decodifica el JWT del header Authorization: Bearer <token>."""
    try:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Formato de autorización inválido. Use: Bearer <token>",
            )
        return decode_token(parts[1])
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Token rechazado: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error verificando token: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
        )


async def verify_admin(authorization: str = Header(...)) -> dict:
    """Verifica que el token pertenece a un usuario con rol admin."""
    payload = await verify_token(authorization)
    if payload.get("rol") != "admin":
        logger.warning(f"Acceso admin denegado a usuario: {payload.get('sub')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden realizar esta acción",
        )
    return payload
