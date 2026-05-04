from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.dependencies import verify_token
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

_COL = "sistema_config"
_DOC_ID = "agentes_config"

_DEFAULTS: dict = {
    "watcher": {"timeout_segundos": 60, "retry_veces": 3},
    "ocr": {"timeout_segundos": 120, "retry_veces": 2},
    "classifier": {"temperatura": 0.7, "max_tokens": 2000},
    "storage": {"timeout_segundos": 30},
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConfigWatcher(BaseModel):
    timeout_segundos: int
    retry_veces: int


class ConfigOcr(BaseModel):
    timeout_segundos: int
    retry_veces: int


class ConfigClassifier(BaseModel):
    temperatura: float
    max_tokens: int


class ConfigStorage(BaseModel):
    timeout_segundos: int


class ConfigAgentes(BaseModel):
    watcher: ConfigWatcher
    ocr: ConfigOcr
    classifier: ConfigClassifier
    storage: ConfigStorage


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/agentes", response_model=ConfigAgentes)
async def obtener_config_agentes(payload: dict = Depends(verify_token)) -> dict:
    """Devuelve la configuración actual de los agentes. Retorna defaults si no existe."""
    try:
        mongo = MongoService()
        doc = mongo.db[_COL].find_one({"_id": _DOC_ID})
        if doc:
            doc.pop("_id", None)
            doc.pop("updated_at", None)
            return doc
        return _DEFAULTS
    except Exception as e:
        logger.error("Error leyendo config agentes: {}", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al leer configuración de agentes")


@router.put("/agentes", response_model=dict)
async def actualizar_config_agentes(
    body: ConfigAgentes,
    payload: dict = Depends(verify_token),
) -> dict:
    """Guarda la configuración de agentes en MongoDB (upsert)."""
    try:
        mongo = MongoService()
        now = datetime.now(timezone.utc).isoformat()
        doc = body.model_dump()
        doc["updated_at"] = now
        mongo.db[_COL].update_one(
            {"_id": _DOC_ID},
            {"$set": doc},
            upsert=True,
        )
        logger.info("Config agentes actualizada por '{}'", payload.get("sub"))
        return {"message": "Configuración guardada"}
    except Exception as e:
        logger.error("Error guardando config agentes: {}", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al guardar configuración de agentes")
