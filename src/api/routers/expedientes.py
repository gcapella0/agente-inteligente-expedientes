from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


@router.get("/docentes")
async def list_docentes(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(10, ge=1, le=100, description="Máximo de registros"),
):
    """Lista todos los docentes con paginación."""
    try:
        mongo = MongoService()
        docentes = list(mongo.docentes.find().skip(skip).limit(limit))
        total = mongo.docentes.count_documents({})

        for doc in docentes:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])

        logger.info(f"Docentes listados: {len(docentes)} (skip={skip}, limit={limit})")
        return {"items": docentes, "total": total, "skip": skip, "limit": limit}
    except Exception as e:
        logger.error(f"Error al listar docentes: {e}")
        raise HTTPException(status_code=500, detail="Error de base de datos")


@router.get("/expediente/{cedula}")
async def get_expediente(cedula: str):
    """Obtiene expediente completo (docente + documentos)."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Docente no encontrado: {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        documentos = list(mongo.documentos.find({"docente_cedula": cedula}))

        docente["_id"] = str(docente["_id"])
        for doc in documentos:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])

        logger.info(f"Expediente obtenido: cedula={cedula}, docs={len(documentos)}")
        return {
            "docente": docente,
            "documentos": documentos,
            "total_documentos": len(documentos),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener expediente {cedula}: {e}")
        raise HTTPException(status_code=500, detail="Error de base de datos")
