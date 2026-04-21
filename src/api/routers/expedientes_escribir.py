from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.dependencies import verify_admin
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


class ActualizarDocenteRequest(BaseModel):
    """Campos actualizables de un docente."""

    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    email_personal: Optional[str] = None
    email_institucional: Optional[str] = None
    telefono_principal: Optional[str] = None
    telefono_secundario: Optional[str] = None
    direccion_completa: Optional[str] = None
    departamento: Optional[str] = None
    sede: Optional[str] = None
    estado_civil: Optional[str] = None
    nacionalidad: Optional[str] = None


_CAMPO_A_RUTA: dict[str, str] = {
    "nombres": "docente.nombres",
    "apellidos": "docente.apellidos",
    "email_personal": "docente.contacto.email_personal",
    "email_institucional": "docente.contacto.email_institucional",
    "telefono_principal": "docente.contacto.telefono_principal",
    "telefono_secundario": "docente.contacto.telefono_secundario",
    "direccion_completa": "docente.direccion.direccion_completa",
    "departamento": "vinculacion_institucional.departamento",
    "sede": "vinculacion_institucional.sede",
    "estado_civil": "docente.estado_civil",
    "nacionalidad": "docente.nacionalidad",
}


@router.put("/{cedula}")
async def actualizar_expediente(
    cedula: str,
    datos: ActualizarDocenteRequest,
    admin_payload: dict = Depends(verify_admin),
):
    """Actualiza campos de un expediente (docente). Solo admin."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Actualizar: docente no encontrado {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        actualizaciones: dict = {
            ruta: getattr(datos, campo)
            for campo, ruta in _CAMPO_A_RUTA.items()
            if getattr(datos, campo) is not None
        }

        if not actualizaciones:
            raise HTTPException(status_code=400, detail="No hay datos para actualizar")

        actualizaciones["updated_at"] = datetime.now()

        resultado = mongo.docentes.update_one(
            {"docente.cedula": cedula},
            {"$set": actualizaciones},
        )

        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        campos = [c for c in actualizaciones if c != "updated_at"]
        logger.info(f"Docente actualizado: cedula={cedula}, campos={campos}")

        mongo.db["auditoria"].insert_one({
            "timestamp": datetime.now(),
            "tipo_evento": "expediente_actualizado",
            "usuario": admin_payload.get("sub"),
            "docente_cedula": cedula,
            "campos_actualizados": campos,
            "resultado": "exitoso",
            "detalles": f"Actualización de {len(campos)} campos",
        })

        return {
            "mensaje": "Expediente actualizado correctamente",
            "cedula": cedula,
            "campos_actualizados": campos,
            "timestamp": datetime.now(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error actualizando expediente {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al actualizar expediente")


@router.delete("/{cedula}")
async def eliminar_expediente(
    cedula: str,
    admin_payload: dict = Depends(verify_admin),
):
    """Elimina un expediente (docente y sus documentos asociados). Solo admin."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Eliminar: docente no encontrado {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        nombre = f"{docente['docente'].get('nombres', '')} {docente['docente'].get('apellidos', '')}".strip()

        docs_eliminados = mongo.documentos.delete_many({"docente_cedula": cedula}).deleted_count
        mongo.docentes.delete_one({"docente.cedula": cedula})

        logger.warning(
            f"Expediente ELIMINADO por {admin_payload.get('sub')}: "
            f"cedula={cedula}, docente={nombre}, docs={docs_eliminados}"
        )

        mongo.db["auditoria"].insert_one({
            "timestamp": datetime.now(),
            "tipo_evento": "expediente_eliminado",
            "usuario": admin_payload.get("sub"),
            "docente_cedula": cedula,
            "resultado": "exitoso",
            "detalles": f"Expediente de {nombre} eliminado con {docs_eliminados} documentos",
        })

        return {
            "mensaje": "Expediente eliminado correctamente",
            "cedula": cedula,
            "docente": nombre,
            "documentos_eliminados": docs_eliminados,
            "timestamp": datetime.now(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando expediente {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al eliminar expediente")
