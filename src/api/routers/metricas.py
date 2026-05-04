from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import verify_token
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


@router.get("/")
async def get_metricas(token: dict = Depends(verify_token)):
    """Retorna 4 métricas clave del sistema. Requiere JWT válido."""
    try:
        mongo = MongoService()

        total_documentos = mongo.documentos.count_documents(
            {"validacion.estado": {"$ne": "rechazado"}}
        )

        pipeline_completitud = [
            {"$group": {"_id": None, "promedio": {"$avg": "$completitud.porcentaje"}}}
        ]
        resultado = list(mongo.docentes.aggregate(pipeline_completitud))
        completitud_promedio = round(resultado[0]["promedio"] or 0, 1) if resultado else 0.0

        docentes_aptos = mongo.docentes.count_documents(
            {"completitud.porcentaje": {"$gte": 80}}
        )
        docentes_totales = mongo.docentes.count_documents({})

        logger.info(
            f"Métricas consultadas por {token.get('sub')}: "
            f"docs={total_documentos}, completitud={completitud_promedio}%, "
            f"aptos={docentes_aptos}/{docentes_totales}"
        )

        return {
            "totalDocumentos": total_documentos,
            "completitudPromedio": completitud_promedio,
            "docentesAptos": docentes_aptos,
            "docentesTotales": docentes_totales,
        }

    except Exception as e:
        logger.error(f"Error obteniendo métricas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error calculando métricas")
