from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


@router.get("/health")
async def health_check():
    """Verificar conectividad con MongoDB."""
    try:
        mongo = MongoService()
        mongo.client.admin.command("ping")
        logger.info("Health check: MongoDB OK")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Health check fallido: {e}")
        raise HTTPException(status_code=503, detail="MongoDB no disponible")
