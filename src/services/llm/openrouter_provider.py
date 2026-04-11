"""Proveedor LLM que usa OpenRouter (API compatible con OpenAI)."""

from __future__ import annotations

import json
import re
import time

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from src import config
from src.core.logger import get_agent_logger
from src.prompts.classify_document import CLASSIFY_AND_EXTRACT_PROMPT
from src.services.llm.abstract_llm_provider import BaseLlmProvider

logger = get_agent_logger("classifier")

_MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

_MAX_RETRIES = 3


class OpenRouterProvider(BaseLlmProvider):
    """Clasifica documentos usando modelos de lenguaje vía OpenRouter.

    Soporta rotación de modelos: intenta el modelo primario y, si recibe
    rate limit, rota a los fallbacks. Errores transitorios se reintentan
    hasta ``_MAX_RETRIES`` veces en el mismo modelo.
    """

    def __init__(self) -> None:
        self.client = OpenAI(
            base_url=config.OPENROUTER_BASE_URL,
            api_key=config.OPENROUTER_API_KEY,
        )
        self._model = config.OPENROUTER_MODEL
        seen: set[str] = set()
        self.models: list[str] = []
        for m in [config.OPENROUTER_MODEL] + config.OPENROUTER_FALLBACK_MODELS:
            if m not in seen:
                seen.add(m)
                self.models.append(m)
        logger.info(
            "OpenRouterProvider inicializado — {} modelo(s): {}",
            len(self.models),
            ", ".join(self.models),
        )

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def model_name(self) -> str:
        return self._model

    def classify_and_extract(self, texto_ocr: str) -> dict:
        """Clasifica el texto OCR con rotación de modelos y reintentos.

        Args:
            texto_ocr: Texto extraído por OCR.

        Returns:
            Diccionario con clasificación normalizada (ver ``BaseLlmProvider``).
        """
        inicio = time.perf_counter()

        for model in self.models:
            for intento in range(_MAX_RETRIES):
                contenido, tokens, rate_limited = self._call_api(texto_ocr, model)

                if rate_limited:
                    logger.warning(
                        "Rate limit en '{}' — rotando al siguiente modelo", model
                    )
                    break

                if contenido is None:
                    continue

                parsed = self._parse_json(contenido)
                if parsed is not None:
                    latencia_ms = round((time.perf_counter() - inicio) * 1000)
                    logger.info(
                        "OpenRouter '{}': {} ms, {} tokens",
                        model,
                        latencia_ms,
                        tokens,
                    )
                    parsed["modelo_llm"] = model
                    parsed["tokens_usados"] = tokens
                    parsed["latencia_ms"] = latencia_ms
                    parsed["provider"] = "openrouter"
                    return parsed

                if intento < _MAX_RETRIES - 1:
                    logger.warning(
                        "Respuesta no es JSON en '{}', reintentando…", model
                    )

        latencia_ms = round((time.perf_counter() - inicio) * 1000)
        logger.error("OpenRouter: todos los modelos agotados tras {} ms", latencia_ms)
        return {
            "valido": False,
            "tipo": "no_valido",
            "razon_rechazo": "Error al parsear respuesta del LLM",
            "campos_extraidos": {},
            "confianza_clasificacion": 0.0,
            "modelo_llm": self._model,
            "tokens_usados": 0,
            "latencia_ms": latencia_ms,
            "provider": "openrouter",
        }

    def health_check(self) -> dict:
        """Verifica conectividad con OpenRouter listando modelos disponibles.

        Returns:
            Diccionario con ``status``, ``provider`` y ``model``.
        """
        try:
            self.client.models.list()
            return {
                "status": "ok",
                "provider": "openrouter",
                "model": self._model,
            }
        except (APIConnectionError, APITimeoutError) as exc:
            return {
                "status": "error",
                "provider": "openrouter",
                "model": self._model,
                "detail": str(exc),
            }
        except Exception as exc:
            return {
                "status": "error",
                "provider": "openrouter",
                "model": self._model,
                "detail": str(exc),
            }

    def _call_api(
        self, texto_ocr: str, model: str
    ) -> tuple[str | None, int, bool]:
        """Llama a la API de OpenRouter.

        Returns:
            Tupla (contenido, tokens_usados, rate_limited).
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CLASSIFY_AND_EXTRACT_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Clasifica el siguiente texto extraído por OCR de "
                            "un documento y extrae los campos relevantes:\n\n"
                            f"{texto_ocr}"
                        ),
                    },
                ],
                max_tokens=1000,
                temperature=0.1,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            logger.error("Error de conexión/timeout con OpenRouter: {}", exc)
            return None, 0, False
        except RateLimitError as exc:
            logger.warning("Rate limit en OpenRouter: {}", exc)
            return None, 0, True
        except Exception as exc:
            logger.error("Error inesperado llamando a OpenRouter: {}", exc)
            return None, 0, False

        contenido = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return contenido, tokens, False

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """Extrae y parsea JSON de la respuesta del LLM."""
        cleaned = text.strip()
        match = _MARKDOWN_FENCE_RE.search(cleaned)
        if match:
            cleaned = match.group(1).strip()
        try:
            result = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return None
        return result if isinstance(result, dict) else None
