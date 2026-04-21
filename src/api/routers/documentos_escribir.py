from __future__ import annotations

from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import verify_admin
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

_ESTADOS_VALIDOS = {"pendiente", "aprobado", "rechazado", "requiere_revision"}


class AgregarDocumentoRequest(BaseModel):
    """Datos para agregar un documento a un expediente."""

    tipo: str
    nombre: str
    descripcion: Optional[str] = None
    archivo_ruta: str
    archivo_nombre_original: str
    archivo_formato: str = "pdf"
    archivo_tamano_bytes: Optional[int] = None


class ActualizarValidacionRequest(BaseModel):
    """Datos para actualizar el estado de validación de un documento."""

    estado: str = Field(..., description="pendiente|aprobado|rechazado|requiere_revision")
    observaciones: Optional[str] = None


@router.post("/{cedula}/agregar-documento", status_code=201)
async def agregar_documento(
    cedula: str,
    documento: AgregarDocumentoRequest,
    admin_payload: dict = Depends(verify_admin),
):
    """Agrega un nuevo documento a un expediente existente. Solo admin."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"AgregarDoc: docente no encontrado {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        ahora = datetime.now()
        doc_dict: dict = {
            "docente_id": str(docente["_id"]),
            "docente_cedula": cedula,
            "tipo": documento.tipo,
            "nombre": documento.nombre,
            "descripcion": documento.descripcion,
            "archivo": {
                "ruta": documento.archivo_ruta,
                "nombre_original": documento.archivo_nombre_original,
                "formato": documento.archivo_formato,
                "tamano_bytes": documento.archivo_tamano_bytes,
                "hash_sha256": None,
                "comprimido": False,
                "metodo_compresion": None,
            },
            "ocr": {
                "procesado": False,
                "fecha_procesamiento": None,
                "motor": None,
                "version_motor": None,
                "confianza_promedio": None,
                "texto_completo": None,
                "idioma_detectado": None,
                "paginas": None,
                "campos_extraidos": {},
            },
            "verificacion_visual": {
                "procesado": False,
                "firma": None,
                "sello": None,
                "fecha_verificacion": None,
                "motor": None,
            },
            "validacion": {
                "estado": "pendiente",
                "es_copia_fiel": None,
                "fecha_emision_documento": None,
                "fecha_vencimiento": None,
                "observaciones": None,
                "validado_por": None,
            },
            "metadata": {
                "metodo_carga": "carga_manual",
                "version_procesamiento": 1,
                "folio": None,
                "pagina_expediente": None,
            },
            "created_at": ahora,
            "updated_at": ahora,
        }

        documento_id = mongo.insert_documento(doc_dict)
        mongo.update_completitud(cedula)

        mongo.db["auditoria"].insert_one({
            "timestamp": datetime.now(),
            "tipo_evento": "documento_agregado",
            "usuario": admin_payload.get("sub"),
            "docente_cedula": cedula,
            "documento_id": documento_id,
            "resultado": "exitoso",
            "detalles": f"Tipo: {documento.tipo}",
        })

        logger.info(f"Documento agregado: cedula={cedula}, tipo={documento.tipo}, id={documento_id}")

        return {
            "mensaje": "Documento agregado correctamente",
            "documento_id": documento_id,
            "docente_cedula": cedula,
            "tipo": documento.tipo,
            "timestamp": ahora,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error agregando documento para {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al agregar documento")


@router.patch("/{documento_id}/validacion")
async def actualizar_validacion(
    documento_id: str,
    validacion: ActualizarValidacionRequest,
    admin_payload: dict = Depends(verify_admin),
):
    """Actualiza el estado de validación de un documento. Solo admin."""
    try:
        try:
            doc_oid = ObjectId(documento_id)
        except Exception:
            raise HTTPException(status_code=422, detail="ID de documento inválido")

        if validacion.estado not in _ESTADOS_VALIDOS:
            raise HTTPException(
                status_code=422,
                detail=f"Estado inválido. Válidos: {', '.join(sorted(_ESTADOS_VALIDOS))}",
            )

        mongo = MongoService()

        documento = mongo.documentos.find_one({"_id": doc_oid})
        if not documento:
            logger.warning(f"Validacion: documento no encontrado {documento_id}")
            raise HTTPException(status_code=404, detail="Documento no encontrado")

        actualizaciones: dict = {
            "validacion.estado": validacion.estado,
            "updated_at": datetime.now(),
        }
        if validacion.observaciones is not None:
            actualizaciones["validacion.observaciones"] = validacion.observaciones

        mongo.documentos.update_one({"_id": doc_oid}, {"$set": actualizaciones})

        cedula = documento.get("docente_cedula")
        if cedula:
            mongo.update_completitud(cedula)

        mongo.db["auditoria"].insert_one({
            "timestamp": datetime.now(),
            "tipo_evento": "validacion_actualizada",
            "usuario": admin_payload.get("sub"),
            "documento_id": documento_id,
            "docente_cedula": cedula,
            "resultado": "exitoso",
            "detalles": f"Estado: {validacion.estado}",
        })

        logger.info(f"Validación actualizada: documento_id={documento_id}, estado={validacion.estado}")

        return {
            "mensaje": "Validación actualizada correctamente",
            "documento_id": documento_id,
            "estado": validacion.estado,
            "timestamp": datetime.now(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error actualizando validación de {documento_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al actualizar validación")


@router.delete("/{documento_id}")
async def eliminar_documento(
    documento_id: str,
    admin_payload: dict = Depends(verify_admin),
):
    """Elimina un documento de un expediente. Solo admin."""
    try:
        try:
            doc_oid = ObjectId(documento_id)
        except Exception:
            raise HTTPException(status_code=422, detail="ID de documento inválido")

        mongo = MongoService()

        documento = mongo.documentos.find_one({"_id": doc_oid})
        if not documento:
            logger.warning(f"Eliminar doc: no encontrado {documento_id}")
            raise HTTPException(status_code=404, detail="Documento no encontrado")

        cedula = documento.get("docente_cedula")
        tipo = documento.get("tipo")
        nombre = documento.get("nombre")

        mongo.documentos.delete_one({"_id": doc_oid})

        if cedula:
            mongo.update_completitud(cedula)

        mongo.db["auditoria"].insert_one({
            "timestamp": datetime.now(),
            "tipo_evento": "documento_eliminado",
            "usuario": admin_payload.get("sub"),
            "documento_id": documento_id,
            "docente_cedula": cedula,
            "resultado": "exitoso",
            "detalles": f"Tipo: {tipo}, nombre: {nombre}",
        })

        logger.warning(
            f"Documento ELIMINADO por {admin_payload.get('sub')}: "
            f"id={documento_id}, cedula={cedula}, tipo={tipo}"
        )

        return {
            "mensaje": "Documento eliminado correctamente",
            "documento_id": documento_id,
            "docente_cedula": cedula,
            "tipo": tipo,
            "timestamp": datetime.now(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando documento {documento_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al eliminar documento")
