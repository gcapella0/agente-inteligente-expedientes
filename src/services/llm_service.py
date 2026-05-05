"""Servicio LLM: orquestador agnóstico al proveedor con compatibilidad hacia atrás.

Modo de uso recomendado (proveedor inyectado)::

    from src.services.llm import create_llm_provider
    service = LlmService(create_llm_provider())

Modo legado (OpenRouter directo, sin cambios)::

    service = LlmService()
"""

from __future__ import annotations

import json
import re

from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError

from src import config
from src.core.logger import get_agent_logger
from src.prompts.classify_document import CLASSIFY_AND_EXTRACT_PROMPT

logger = get_agent_logger("classifier")

_MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


class LlmService:
    """Orquestador LLM agnóstico al proveedor.

    Cuando se instancia con un ``provider`` (``BaseLlmProvider``), delega toda
    la lógica a él. Cuando se instancia sin argumentos, usa OpenRouter
    directamente para conservar compatibilidad con código y tests existentes.

    En ambos modos expone la misma interfaz pública:
    ``classify_and_extract(texto_ocr)`` y ``health_check()``.
    """

    def __init__(self, provider=None) -> None:
        if provider is not None:
            # Modo proveedor: delega todo al provider inyectado
            self._delegate = provider
            self.model = provider.model_name
            self.models = getattr(provider, "models", [provider.model_name])
            self.client = None
        else:
            # Modo legado: OpenRouter directo (mantiene compatibilidad con tests)
            self._delegate = None
            self.client = OpenAI(
                base_url=config.OPENROUTER_BASE_URL,
                api_key=config.OPENROUTER_API_KEY,
            )
            self.model = config.OPENROUTER_MODEL
            seen: set[str] = set()
            self.models: list[str] = []
            for m in [config.OPENROUTER_MODEL] + config.OPENROUTER_FALLBACK_MODELS:
                if m not in seen:
                    seen.add(m)
                    self.models.append(m)
            logger.info(
                "LlmService inicializado — {} modelo(s) disponible(s): {}",
                len(self.models),
                ", ".join(self.models),
            )

    _MAX_RETRIES = 3

    def classify_and_extract(self, texto_ocr: str) -> dict:
        """Clasifica un documento y extrae campos estructurados mediante LLM.

        Si se inyectó un proveedor, delega a él. Si no, usa OpenRouter directo
        con rotación de modelos y reintentos exponenciales ante rate limit.

        Args:
            texto_ocr: Texto completo extraído por OCR.

        Returns:
            Diccionario con la clasificación, tipo, campos extraídos y
            metadatos de la respuesta (modelo, tokens usados).
        """
        delegate = getattr(self, "_delegate", None)
        if delegate is not None:
            return delegate.classify_and_extract(texto_ocr)

        # Camino legado: OpenRouter directo
        for model in self.models:
            for intento in range(self._MAX_RETRIES):
                respuesta_raw, tokens_usados, rate_limited = self._call_llm(
                    texto_ocr, model
                )

                if rate_limited:
                    logger.warning(
                        "Rate limit en '{}' — rotando al siguiente modelo", model
                    )
                    break

                if respuesta_raw is None:
                    continue

                parsed = self._parse_json(respuesta_raw)
                if parsed is not None:
                    parsed["modelo_llm"] = model
                    parsed["tokens_usados"] = tokens_usados
                    return parsed

                if intento < self._MAX_RETRIES - 1:
                    logger.warning(
                        "Respuesta no es JSON válido en '{}', reintentando…", model
                    )

        logger.error(
            "No se pudo obtener JSON válido tras agotar todos los modelos disponibles"
        )
        return {
            "valido": False,
            "tipo": "no_valido",
            "razon_rechazo": "Error al parsear respuesta del LLM",
            "campos_extraidos": {},
            "confianza_clasificacion": 0.0,
            "modelo_llm": self.model,
            "tokens_usados": 0,
        }

    def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> str:
        """Envía una pregunta libre al LLM y devuelve la respuesta como texto.

        Requiere que se haya inyectado un proveedor en el constructor.

        Args:
            system: Prompt de sistema.
            user: Pregunta/contexto del usuario.
            max_tokens: Máximo de tokens en la respuesta.
            temperature: Aleatoriedad (0.0–1.0).

        Returns:
            Texto plano con la respuesta del modelo.

        Raises:
            RuntimeError: Si no hay provider inyectado o el backend falla.
        """
        delegate = getattr(self, "_delegate", None)
        if delegate is None:
            raise RuntimeError(
                "LlmService.chat requiere un provider inyectado "
                "(use LlmService(create_llm_provider()))"
            )
        return delegate.chat(system, user, max_tokens=max_tokens, temperature=temperature)

    def health_check(self) -> dict:
        """Verifica que el backend LLM esté disponible.

        Returns:
            Diccionario con ``status``, ``provider`` y ``model``.
        """
        delegate = getattr(self, "_delegate", None)
        if delegate is not None:
            return delegate.health_check()
        # Modo legado: no hay health check real disponible
        return {
            "status": "ok",
            "provider": "openrouter",
            "model": self.model,
        }

    def _call_llm(self, texto_ocr: str, model: str) -> tuple[str | None, int, bool]:
        """Realiza la llamada al LLM y retorna el contenido y tokens usados.

        Args:
            texto_ocr: Texto a clasificar.
            model: Identificador del modelo a usar en esta llamada.

        Returns:
            Tupla (contenido_respuesta, tokens_usados, rate_limited).
            Si ocurre un error de red/API, retorna (None, 0, False).
            Si es rate limit, retorna (None, 0, True).
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
            logger.warning("Rate limit alcanzado en OpenRouter: {}", exc)
            return None, 0, True
        except Exception as exc:
            logger.error("Error inesperado al llamar al LLM: {}", exc)
            return None, 0, False

        contenido = response.choices[0].message.content or ""
        tokens = 0
        if response.usage:
            tokens = response.usage.total_tokens
        return contenido, tokens, False

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """Intenta parsear JSON de la respuesta del LLM.

        Elimina bloques de código markdown si están presentes.
        """
        cleaned = text.strip()

        match = _MARKDOWN_FENCE_RE.search(cleaned)
        if match:
            cleaned = match.group(1).strip()

        try:
            result = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(result, dict):
            return None

        return result
