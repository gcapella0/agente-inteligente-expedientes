from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import verify_admin
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

_CAMPOS_SEGUROS = {"timestamp", "tipo_evento", "usuario", "detalles", "resultado"}


def _sanitizar_evento(evento: dict) -> dict:
    """Devuelve solo campos seguros del evento (sin rutas, IPs internas, etc.)."""
    return {k: v for k, v in evento.items() if k in _CAMPOS_SEGUROS}


@router.get("/expediente/{cedula}")
async def auditoria_expediente(
    cedula: str,
    dias: int = Query(7, ge=1, le=90, description="Rango de días hacia atrás"),
    admin_payload: dict = Depends(verify_admin),
) -> dict:
    """Historial de auditoría de un expediente (solo admin)."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Auditoría solicitada para docente inexistente: {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        fecha_desde = datetime.now() - timedelta(days=dias)
        audit_col = mongo.db["auditoria"]

        eventos = list(
            audit_col.find(
                {"docente_cedula": cedula, "timestamp": {"$gte": fecha_desde}}
            ).sort("timestamp", -1).limit(100)
        )

        logger.info(
            f"Auditoría de expediente {cedula} consultada por {admin_payload.get('sub')}"
        )

        return {
            "docente_cedula": cedula,
            "rango_dias": dias,
            "fecha_desde": fecha_desde,
            "total_eventos": len(eventos),
            "eventos": [_sanitizar_evento(e) for e in eventos],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en auditoría de {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al obtener auditoría")


@router.get("/documento/{documento_id}")
async def auditoria_documento(
    documento_id: str,
    admin_payload: dict = Depends(verify_admin),
) -> dict:
    """Historial de cambios de un documento (solo admin)."""
    try:
        mongo = MongoService()
        audit_col = mongo.db["auditoria"]

        eventos = list(
            audit_col.find({"documento_id": documento_id}).sort("timestamp", -1)
        )

        logger.info(
            f"Auditoría de documento {documento_id} consultada por {admin_payload.get('sub')}"
        )

        return {
            "documento_id": documento_id,
            "total_eventos": len(eventos),
            "eventos": [_sanitizar_evento(e) for e in eventos],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en auditoría de documento {documento_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al obtener auditoría")
