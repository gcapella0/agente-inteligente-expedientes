from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.api.dependencies import verify_admin
from src.api.security import hash_password
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

_ROLES_VALIDOS = {"admin", "docente", "viewer"}


class UsuarioCrear(BaseModel):
    email: str
    password: str
    rol: str = "docente"


class RolUpdate(BaseModel):
    rol: str


def _serializar_usuario(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "email": doc.get("email", ""),
        "rol": doc.get("rol", ""),
        "createdAt": doc.get("creado_en", doc.get("createdAt", "")).isoformat()
        if isinstance(doc.get("creado_en", doc.get("createdAt")), datetime)
        else str(doc.get("creado_en", doc.get("createdAt", ""))),
    }


@router.get("/")
async def listar_usuarios(admin_payload: dict = Depends(verify_admin)) -> list[dict]:
    """Lista todos los usuarios sin exponer el campo password_hash."""
    try:
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]
        docs = list(usuarios_col.find({}, {"password_hash": 0}))
        return [_serializar_usuario(d) for d in docs]
    except Exception as e:
        logger.error(f"Error listando usuarios: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al obtener usuarios")


@router.post("/crear", status_code=201)
async def crear_usuario(
    nuevo: UsuarioCrear,
    admin_payload: dict = Depends(verify_admin),
) -> dict:
    """Crea un nuevo usuario. Solo admin."""
    if "@" not in nuevo.email:
        raise HTTPException(status_code=400, detail="Email inválido")
    if len(nuevo.password) < 6:
        raise HTTPException(status_code=400, detail="Password debe tener mínimo 6 caracteres")
    if nuevo.rol not in _ROLES_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Rol inválido. Valores permitidos: {sorted(_ROLES_VALIDOS)}")

    try:
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]

        if usuarios_col.find_one({"email": nuevo.email}):
            raise HTTPException(status_code=400, detail="El email ya está registrado")

        ahora = datetime.now()
        resultado = usuarios_col.insert_one({
            "email": nuevo.email,
            "password_hash": hash_password(nuevo.password),
            "rol": nuevo.rol,
            "activo": True,
            "creado_en": ahora,
            "actualizado_en": ahora,
        })

        logger.warning(
            f"Usuario creado por {admin_payload.get('sub')}: {nuevo.email}, rol: {nuevo.rol}"
        )
        return {
            "id": str(resultado.inserted_id),
            "email": nuevo.email,
            "rol": nuevo.rol,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando usuario: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al crear usuario")


@router.put("/{user_id}/rol")
async def actualizar_rol(
    user_id: str,
    rol_update: RolUpdate,
    admin_payload: dict = Depends(verify_admin),
) -> dict:
    """Actualiza el rol de un usuario. Solo admin."""
    if rol_update.rol not in _ROLES_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Rol inválido. Valores permitidos: {sorted(_ROLES_VALIDOS)}")

    try:
        oid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID de usuario inválido")

    try:
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]
        resultado = usuarios_col.update_one(
            {"_id": oid},
            {"$set": {"rol": rol_update.rol, "actualizado_en": datetime.now()}},
        )
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        logger.info(f"Rol actualizado para {user_id} → {rol_update.rol} por {admin_payload.get('sub')}")
        return {"message": "Rol actualizado"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error actualizando rol: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al actualizar rol")


@router.delete("/{user_id}")
async def eliminar_usuario(
    user_id: str,
    admin_payload: dict = Depends(verify_admin),
) -> dict:
    """Elimina un usuario. Solo admin."""
    try:
        oid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID de usuario inválido")

    try:
        mongo = MongoService()
        usuarios_col = mongo.db["usuarios"]
        resultado = usuarios_col.delete_one({"_id": oid})
        if resultado.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        logger.warning(f"Usuario eliminado: {user_id} por {admin_payload.get('sub')}")
        return {"message": "Usuario eliminado"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando usuario: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al eliminar usuario")
