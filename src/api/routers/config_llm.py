from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Literal

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from src import config
from src.api.dependencies import verify_token
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

_COL = "sistema_config"
_DOC_ID = "llm_config"
_PROVIDERS_VALIDOS = {"openrouter", "ollama"}

def _openrouter_models_from_env() -> list[str]:
    """Devuelve la lista de modelos OpenRouter desde el .env (modelo principal + fallbacks)."""
    modelos: list[str] = []
    seen: set[str] = set()
    for m in [config.OPENROUTER_MODEL] + config.OPENROUTER_FALLBACK_MODELS:
        if m and m not in seen:
            seen.add(m)
            modelos.append(m)
    return modelos or ["openai/gpt-4o-mini"]


def _ollama_models_from_env() -> list[str]:
    """Devuelve la lista de modelos Ollama desde el .env."""
    raw = os.getenv("OLLAMA_MODELS", "")
    modelos = [m.strip() for m in raw.split(",") if m.strip()]
    if not modelos and config.OLLAMA_MODEL:
        modelos = [config.OLLAMA_MODEL]
    return modelos or ["phi3:mini"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LlmConfigResponse(BaseModel):
    provider: str
    model: str
    host: str | None
    available_providers: list[str]
    available_models_ollama: list[str]
    available_models_openrouter: list[str]


class LlmConfigUpdate(BaseModel):
    provider: Literal["openrouter", "ollama"]
    model: str
    host: str | None = None


class ProbarResponse(BaseModel):
    ok: bool
    latencia_ms: int | None
    provider: str
    modelos_disponibles: list[str] | None
    error: str | None
    mensaje: str


# ---------------------------------------------------------------------------
# Helper: leer config vigente desde Mongo o defaults de .env
# ---------------------------------------------------------------------------


def _leer_config(mongo: MongoService) -> dict:
    doc = mongo.db[_COL].find_one({"_id": _DOC_ID})
    if doc:
        return doc
    return {
        "provider": config.LLM_PROVIDER,
        "model": config.OPENROUTER_MODEL if config.LLM_PROVIDER == "openrouter" else config.OLLAMA_MODEL,
        "host": config.OLLAMA_BASE_URL if config.LLM_PROVIDER == "ollama" else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/llm", response_model=LlmConfigResponse)
async def obtener_config_llm(payload: dict = Depends(verify_token)) -> dict:
    """Devuelve la configuración actual del proveedor LLM."""
    try:
        mongo = MongoService()
        cfg = _leer_config(mongo)
        return {
            "provider": cfg.get("provider", config.LLM_PROVIDER),
            "model": cfg.get("model", ""),
            "host": cfg.get("host"),
            "available_providers": sorted(_PROVIDERS_VALIDOS),
            "available_models_ollama": _ollama_models_from_env(),
            "available_models_openrouter": _openrouter_models_from_env(),
        }
    except Exception as e:
        logger.error("Error leyendo config LLM: {}", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al leer configuración LLM")


@router.put("/llm", response_model=dict)
async def actualizar_config_llm(
    body: LlmConfigUpdate,
    payload: dict = Depends(verify_token),
) -> dict:
    """Actualiza el proveedor LLM en MongoDB."""
    if body.provider == "ollama" and not body.host:
        raise HTTPException(
            status_code=400,
            detail="'host' es requerido cuando provider='ollama'",
        )
    try:
        mongo = MongoService()
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "provider": body.provider,
            "model": body.model,
            "host": body.host,
            "updated_at": now,
        }
        mongo.db[_COL].update_one(
            {"_id": _DOC_ID},
            {"$set": doc},
            upsert=True,
        )
        logger.info(
            "Config LLM actualizada: provider='{}' model='{}' por '{}'",
            body.provider, body.model, payload.get("sub"),
        )
        return {
            "provider": body.provider,
            "model": body.model,
            "host": body.host,
            "timestamp": now,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando config LLM: {}", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al actualizar configuración LLM")


@router.post("/llm/probar", response_model=ProbarResponse)
async def probar_conexion_llm(payload: dict = Depends(verify_token)) -> dict:
    """Testea la conexión con el proveedor LLM configurado."""
    try:
        mongo = MongoService()
        cfg = _leer_config(mongo)
        provider = cfg.get("provider", config.LLM_PROVIDER)
        host = cfg.get("host") or config.OLLAMA_BASE_URL

        inicio = time.perf_counter()

        if provider == "ollama":
            try:
                resp = requests.get(f"{host}/api/tags", timeout=5)
                resp.raise_for_status()
                latencia_ms = round((time.perf_counter() - inicio) * 1000)
                data = resp.json()
                modelos = [m.get("name", "") for m in data.get("models", [])]
                return {
                    "ok": True,
                    "latencia_ms": latencia_ms,
                    "provider": "ollama",
                    "modelos_disponibles": modelos,
                    "error": None,
                    "mensaje": "Conexión exitosa",
                }
            except requests.exceptions.ConnectionError:
                return {
                    "ok": False,
                    "latencia_ms": None,
                    "provider": "ollama",
                    "modelos_disponibles": None,
                    "error": f"Connection refused: {host} no responde",
                    "mensaje": "No se pudo conectar al servidor",
                }
            except requests.exceptions.Timeout:
                return {
                    "ok": False,
                    "latencia_ms": None,
                    "provider": "ollama",
                    "modelos_disponibles": None,
                    "error": f"Timeout al conectar con {host}",
                    "mensaje": "No se pudo conectar al servidor",
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "latencia_ms": None,
                    "provider": "ollama",
                    "modelos_disponibles": None,
                    "error": str(exc),
                    "mensaje": "No se pudo conectar al servidor",
                }

        # OpenRouter
        from src.services.llm.openrouter_provider import OpenRouterProvider
        or_provider = OpenRouterProvider()
        resultado = or_provider.health_check()
        latencia_ms = round((time.perf_counter() - inicio) * 1000)
        ok = resultado.get("status") == "ok"
        return {
            "ok": ok,
            "latencia_ms": latencia_ms,
            "provider": "openrouter",
            "modelos_disponibles": None,
            "error": resultado.get("detail") if not ok else None,
            "mensaje": "Conexión exitosa" if ok else "No se pudo conectar al servidor",
        }

    except Exception as e:
        logger.error("Error probando conexión LLM: {}", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al probar conexión LLM")
