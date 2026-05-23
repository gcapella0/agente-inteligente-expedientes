"""Proveedor LLM que usa Ollama corriendo localmente."""

from __future__ import annotations

import json
import os
import re
import time

import requests

from src import config
from src.core.logger import get_agent_logger
from src.prompts.classify_document import CLASSIFY_AND_EXTRACT_PROMPT
from src.services.llm.abstract_llm_provider import BaseLlmProvider

logger = get_agent_logger("classifier")

_MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

# Límite de caracteres del texto OCR enviado a Ollama (CPU-friendly).
# El system prompt (~4400 chars) se envía separado vía /api/chat.
_PROMPT_MAX_CHARS = 1500

# Número de hilos de CPU a usar. Por defecto usa todos los disponibles.
_NUM_THREADS = int(os.getenv("OLLAMA_NUM_THREADS", str(os.cpu_count() or 4)))


class OllamaProvider(BaseLlmProvider):
    """Clasifica documentos usando un modelo Ollama corriendo en CPU local.

    Usa ``POST /api/generate`` con ``stream=False``. El timeout es amplio
    porque la inferencia en CPU puede tardar 30-60 segundos con Mistral 7B.
    En caso de respuesta no JSON, reintenta una sola vez antes de fallar.
    """

    def __init__(self) -> None:
        self._model = config.OLLAMA_MODEL
        self._base_url = config.OLLAMA_BASE_URL.rstrip("/")
        self._timeout = config.OLLAMA_TIMEOUT_SECONDS
        self._num_predict = config.OLLAMA_NUM_PREDICT
        logger.info(
            "OllamaProvider inicializado — modelo: '{}', base_url: {}, timeout: {}s, "
            "num_predict: {}, num_threads: {}",
            self._model,
            self._base_url,
            self._timeout,
            self._num_predict,
            _NUM_THREADS,
        )

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def classify_and_extract(self, texto_ocr: str) -> dict:
        """Clasifica el texto OCR usando Ollama vía ``/api/chat``.

        Separa el system prompt del contenido OCR para mayor eficiencia.
        Trunca el texto OCR a ``_PROMPT_MAX_CHARS`` para acotar el contexto
        en CPU. Reintenta una vez si la respuesta no es JSON válido.

        Args:
            texto_ocr: Texto extraído por OCR.

        Returns:
            Diccionario con clasificación normalizada (ver ``BaseLlmProvider``).
        """
        texto_truncado = texto_ocr[:_PROMPT_MAX_CHARS]
        mensajes = [
            {"role": "system", "content": CLASSIFY_AND_EXTRACT_PROMPT},
            {
                "role": "user",
                "content": (
                    "Clasifica el siguiente texto extraído por OCR de un documento "
                    "y extrae los campos relevantes:\n\n"
                    f"{texto_truncado}"
                ),
            },
        ]

        inicio = time.perf_counter()

        for intento in range(2):  # máx 2 intentos
            contenido, bytes_resp = self._call_api(mensajes)

            if contenido is None:
                latencia_ms = round((time.perf_counter() - inicio) * 1000)
                return self._error_result(latencia_ms, "Ollama no respondió")

            parsed = self._parse_json(contenido)
            if parsed is not None:
                latencia_ms = round((time.perf_counter() - inicio) * 1000)
                logger.info(
                    "Ollama '{}': {} ms, {} bytes recibidos",
                    self._model,
                    latencia_ms,
                    bytes_resp,
                )
                parsed["modelo_llm"] = self._model
                parsed["tokens_usados"] = None
                parsed["latencia_ms"] = latencia_ms
                parsed["provider"] = "ollama"
                return parsed

            if intento == 0:
                logger.warning(
                    "Ollama: respuesta no es JSON válido, reintentando…"
                )

        latencia_ms = round((time.perf_counter() - inicio) * 1000)
        logger.error("Ollama: no se obtuvo JSON válido tras 2 intentos ({} ms)", latencia_ms)
        return self._error_result(latencia_ms, "Respuesta no es JSON válido")

    def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> str:
        """Envía una pregunta libre a Ollama y devuelve la respuesta como texto.

        No reutiliza ``_call_api`` para poder controlar ``num_predict`` y
        ``temperature`` independientemente del valor configurado en el provider.

        Args:
            system: Prompt de sistema.
            user: Pregunta/contexto del usuario.
            max_tokens: Máximo de tokens en la respuesta (``num_predict``).
            temperature: Aleatoriedad (0.0–1.0).

        Returns:
            Texto plano con la respuesta del modelo.

        Raises:
            RuntimeError: Si Ollama no responde o devuelve un error.
        """
        mensajes = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        payload = {
            "model": self._model,
            "messages": mensajes,
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "num_predict": max_tokens,
                "num_ctx": 2048,
                "num_thread": _NUM_THREADS,
                "temperature": temperature,
            },
        }
        inicio = time.perf_counter()
        try:
            resp = requests.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"Ollama: timeout tras {self._timeout}s al responder pregunta"
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"Ollama: error de conexión — {exc}")
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(f"Ollama: error HTTP {resp.status_code} — {exc}")

        latencia_ms = round((time.perf_counter() - inicio) * 1000)
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Ollama: respuesta no es JSON — {exc}")

        contenido = data.get("message", {}).get("content", "")
        logger.info("Ollama chat '{}': {} ms", self._model, latencia_ms)
        return contenido

    def health_check(self) -> dict:
        """Verifica que Ollama esté corriendo consultando ``/api/tags``.

        Returns:
            Diccionario con ``status`` ("ok" | "error"), ``provider``, ``model``
            y opcionalmente ``detail`` con el mensaje de error.
        """
        try:
            resp = requests.get(
                f"{self._base_url}/api/tags",
                timeout=5,
            )
            resp.raise_for_status()
            return {"status": "ok", "provider": "ollama", "model": self._model}
        except requests.exceptions.ConnectionError:
            return {
                "status": "error",
                "provider": "ollama",
                "model": self._model,
                "detail": f"Ollama no disponible en {self._base_url}",
            }
        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "provider": "ollama",
                "model": self._model,
                "detail": "Timeout al conectar con Ollama",
            }
        except requests.exceptions.HTTPError as exc:
            return {
                "status": "error",
                "provider": "ollama",
                "model": self._model,
                "detail": str(exc),
            }

    def _call_api(self, mensajes: list[dict]) -> tuple[str | None, int]:
        """Llama a ``POST /api/chat`` de Ollama.

        Usa el endpoint de chat para separar system prompt de user content.
        Limita el contexto a 2048 tokens y usa todos los hilos de CPU disponibles.

        Args:
            mensajes: Lista de mensajes con ``role`` y ``content``.

        Returns:
            Tupla (contenido_respuesta, bytes_recibidos).
            Si hay error, retorna (None, 0).
        """
        payload = {
            "model": self._model,
            "messages": mensajes,
            "stream": False,
            "keep_alive": "24h",
            "options": {
                "num_predict": 300,
                "num_ctx": 2048,
                "num_thread": _NUM_THREADS,
            },
        }
        try:
            resp = requests.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            logger.error(
                "Ollama: timeout tras {}s — considera usar un modelo más pequeño "
                "(qwen2.5:0.5b, phi3:mini) o reducir OLLAMA_NUM_PREDICT",
                self._timeout,
            )
            return None, 0
        except requests.exceptions.ConnectionError as exc:
            logger.error("Ollama: error de conexión — {}", exc)
            return None, 0
        except requests.exceptions.HTTPError as exc:
            logger.error("Ollama: error HTTP {} — {}", resp.status_code, exc)
            return None, 0

        bytes_recibidos = len(resp.content)
        try:
            data = resp.json()
        except ValueError as exc:
            logger.error("Ollama: respuesta no es JSON — {}", exc)
            return None, bytes_recibidos

        contenido = data.get("message", {}).get("content", "")
        return contenido, bytes_recibidos

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

    def _error_result(self, latencia_ms: int, razon: str) -> dict:
        return {
            "valido": False,
            "tipo": "no_valido",
            "razon_rechazo": razon,
            "campos_extraidos": {},
            "confianza_clasificacion": 0.0,
            "modelo_llm": self._model,
            "tokens_usados": None,
            "latencia_ms": latencia_ms,
            "provider": "ollama",
        }
