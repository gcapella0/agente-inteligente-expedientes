"""Factory para instanciar el proveedor LLM configurado en .env."""

from __future__ import annotations

from src import config
from src.services.llm.abstract_llm_provider import BaseLlmProvider


def create_llm_provider() -> BaseLlmProvider:
    """Crea e instancia el proveedor LLM según ``LLM_PROVIDER`` en .env.

    Proveedores soportados:
    - ``"openrouter"`` (por defecto): usa la API de OpenRouter.
    - ``"ollama"``: usa un servidor Ollama local.

    Returns:
        Instancia concreta de ``BaseLlmProvider``.

    Raises:
        ValueError: Si ``LLM_PROVIDER`` tiene un valor no reconocido.
    """
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
