from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import verify_admin, verify_token
from src.api.security import create_access_token, hash_password, verify_password
from src.core.logger import get_agent_logger
from src.models.usuario import LoginRequest, TokenResponse, UsuarioCreate, UsuarioResponse
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


def init_usuarios() -> None:
    """Inicializa la colección de usuarios con el admin por defecto si está vacía."""
    try:
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]
        usuarios_col.create_index("email", unique=True, sparse=True)

        if usuarios_col.count_documents({}) == 0:
            usuarios_col.insert_one({
                "email": "admin@uneg.edu.ve",
                "password_hash": hash_password("admin123"),
                "nombre_completo": "Administrador Sistema",
                "rol": "admin",
                "activo": True,
                "ultimo_login": None,
                "creado_en": datetime.now(),
                "actualizado_en": datetime.now(),
            })
            logger.warning("Usuario admin creado: admin@uneg.edu.ve / admin123 — CAMBIAR EN PRODUCCIÓN")
    except Exception as e:
        logger.error(f"Error inicializando colección de usuarios: {e}")


@router.post("/login", response_model=TokenResponse)
async def login(credenciales: LoginRequest) -> TokenResponse:
    """Autentica usuario y devuelve JWT token."""
    try:
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]

        usuario = usuarios_col.find_one({"email": credenciales.email})
        if not usuario:
            logger.warning(f"Login fallido — email no registrado: {credenciales.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o contraseña incorrectos",
            )

        if not verify_password(credenciales.password, usuario["password_hash"]):
            logger.warning(f"Login fallido — contraseña incorrecta: {credenciales.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o contraseña incorrectos",
            )

        if not usuario.get("activo", False):
            logger.warning(f"Login denegado — usuario inactivo: {credenciales.email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario inactivo",
            )

        token = create_access_token(
            subject=usuario["email"],
            rol=usuario["rol"],
            expires_delta=timedelta(hours=8),
        )

        usuarios_col.update_one(
            {"email": credenciales.email},
            {"$set": {"ultimo_login": datetime.now()}},
        )

        logger.info(f"Login exitoso: {credenciales.email}, rol: {usuario['rol']}")

        return TokenResponse(
            access_token=token,
            usuario=UsuarioResponse(
                email=usuario["email"],
                nombre_completo=usuario["nombre_completo"],
                rol=usuario["rol"],
                activo=usuario["activo"],
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en login: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error en autenticación")


@router.post("/crear-usuario", status_code=201)
async def crear_usuario(
    nuevo_usuario: UsuarioCreate,
    admin_payload: dict = Depends(verify_admin),
) -> dict:
    """Crea un nuevo usuario. Solo admin."""
    try:
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]

        if usuarios_col.find_one({"email": nuevo_usuario.email}):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El email ya está registrado",
            )

        ahora = datetime.now()
        resultado = usuarios_col.insert_one({
            "email": nuevo_usuario.email,
            "password_hash": hash_password(nuevo_usuario.password),
            "nombre_completo": nuevo_usuario.nombre_completo,
            "rol": nuevo_usuario.rol,
            "activo": True,
            "ultimo_login": None,
            "creado_en": ahora,
            "actualizado_en": ahora,
        })

        logger.warning(
            f"Nuevo usuario creado por {admin_payload.get('sub')}: "
            f"{nuevo_usuario.email}, rol: {nuevo_usuario.rol}"
        )

        return {
            "mensaje": "Usuario creado correctamente",
            "_id": str(resultado.inserted_id),
            "email": nuevo_usuario.email,
            "rol": nuevo_usuario.rol,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando usuario: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al crear usuario")


@router.post("/cambiar-password")
async def cambiar_password(
    password_actual: str,
    password_nuevo: str,
    payload: dict = Depends(verify_token),
) -> dict:
    """Cambia la contraseña del usuario autenticado."""
    try:
        email = payload.get("sub")
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]

        usuario = usuarios_col.find_one({"email": email})
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        if not verify_password(password_actual, usuario["password_hash"]):
            logger.warning(f"Cambio de contraseña rechazado — contraseña actual incorrecta: {email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Contraseña actual incorrecta",
            )

        usuarios_col.update_one(
            {"email": email},
            {"$set": {"password_hash": hash_password(password_nuevo), "actualizado_en": datetime.now()}},
        )

        logger.info(f"Contraseña actualizada para: {email}")
        return {"mensaje": "Contraseña cambiada correctamente", "email": email}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cambiando contraseña: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al cambiar contraseña")
