"""Factory para instanciar el proveedor LLM configurado."""

from __future__ import annotations

from src import config
from src.services.llm.abstract_llm_provider import BaseLlmProvider


def create_llm_provider() -> BaseLlmProvider:
    """Crea e instancia el proveedor LLM.

    Prioridad de configuración:
    1. MongoDB (colección ``sistema_config``, doc ``llm_config``).
    2. Variables de entorno en ``.env`` (via ``src/config.py``).

    Proveedores soportados: ``"openrouter"`` y ``"ollama"``.

    Raises:
        ValueError: Si el proveedor configurado no es reconocido.
    """
    # Prioridad 1: Mongo — sobreescribe config.* si existe el documento
    try:
        from src.services.mongo_service import MongoService
        mongo = MongoService()
        doc = mongo.db["sistema_config"].find_one({"_id": "llm_config"})
        if doc:
            config.LLM_PROVIDER = doc["provider"]
            if doc["provider"] == "ollama":
                config.OLLAMA_MODEL = doc.get("model") or config.OLLAMA_MODEL
                config.OLLAMA_BASE_URL = doc.get("host") or config.OLLAMA_BASE_URL
            else:
                config.OPENROUTER_MODEL = doc.get("model") or config.OPENROUTER_MODEL
    except Exception:
        pass  # Mongo no disponible → fallback silencioso a .env

    provider = config.LLM_PROVIDER.lower().strip()

    if provider == "openrouter":
        from src.services.llm.openrouter_provider import OpenRouterProvider
        return OpenRouterProvider()

    if provider == "ollama":
        from src.services.llm.ollama_provider import OllamaProvider
        return OllamaProvider()

    raise ValueError(
        f"Proveedor LLM no reconocido: '{config.LLM_PROVIDER}'. "
        "Valores válidos: 'openrouter', 'ollama'."
    )
