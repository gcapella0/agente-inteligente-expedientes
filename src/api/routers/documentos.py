from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, HTTPException

from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


@router.get("/{documento_id}")
async def obtener_documento(documento_id: str):
    """Obtiene detalle completo de un documento."""
    try:
        try:
            doc_oid = ObjectId(documento_id)
        except Exception:
            raise HTTPException(status_code=422, detail="ID de documento inválido")

        mongo = MongoService()
        documento = mongo.documentos.find_one({"_id": doc_oid})

        if not documento:
            logger.warning(f"Documento no encontrado: {documento_id}")
            raise HTTPException(status_code=404, detail="Documento no encontrado")

        documento["_id"] = str(documento["_id"])
        logger.info(f"Documento obtenido: {documento_id}")
        return documento

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo documento {documento_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error de base de datos")


@router.get("/{documento_id}/validacion")
async def validacion_documento(documento_id: str):
    """Obtiene validaciones de un documento."""
    try:
        try:
            doc_oid = ObjectId(documento_id)
        except Exception:
            raise HTTPException(status_code=422, detail="ID de documento inválido")

        mongo = MongoService()
        documento = mongo.documentos.find_one({"_id": doc_oid})

        if not documento:
            logger.warning(f"Documento no encontrado para validación: {documento_id}")
            raise HTTPException(status_code=404, detail="Documento no encontrado")

        archivo = documento.get("archivo", {})
        ocr = documento.get("ocr", {})

        validaciones = {
            "formato": {
                "valido": archivo.get("formato") in ["pdf", "jpg", "jpeg", "png"],
                "tipo_esperado": "pdf",
                "tamano_dentro_rango": archivo.get("tamano_bytes", 0) <= 25 * 1024 * 1024,
                "detalle": f"{archivo.get('tamano_bytes', 0) // 1024} KB",
            },
            "ocr_confiabilidad": {
                "confianza_promedio": ocr.get("confianza_promedio"),
                "paginas_con_baja_confianza": [],
                "idioma_consistente": ocr.get("idioma_detectado") == "es",
            },
            "metadatos_extraidos": ocr.get("campos_extraidos", {}),
        }

        es_valido = (
            validaciones["formato"]["valido"]
            and validaciones["formato"]["tamano_dentro_rango"]
            and documento.get("validacion", {}).get("estado") == "aprobado"
        )

        logger.info(f"Validación de documento: {documento_id}, válido={es_valido}")
        return {
            "_id": str(documento["_id"]),
            "validaciones": validaciones,
            "es_valido_para_expediente": es_valido,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validando documento {documento_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error de base de datos")
