"""Contrato base para todos los proveedores LLM."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLlmProvider(ABC):
    """Interfaz que deben implementar todos los proveedores LLM.

    Cada implementación concreta gestiona la comunicación con un backend
    específico (OpenRouter, Ollama, etc.) y devuelve resultados en el mismo
    formato normalizado.

    Formato de retorno de ``classify_and_extract``::

        {
            "valido": bool,
            "tipo": str,
            "campos_extraidos": dict,
            "confianza_clasificacion": float,
            "razon_rechazo": str | None,
            "modelo_llm": str,
            "tokens_usados": int | None,   # None si el backend no lo reporta
            "latencia_ms": int,
            "provider": str,
        }
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identificador del proveedor, p. ej. "openrouter" o "ollama"."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Modelo principal activo en este proveedor."""

    @abstractmethod
    def classify_and_extract(self, texto_ocr: str) -> dict:
        """Clasifica el texto OCR y extrae campos estructurados.

        Args:
            texto_ocr: Texto extraído por OCR del documento.

        Returns:
            Diccionario con el resultado de clasificación normalizado.
        """

    @abstractmethod
    def health_check(self) -> dict:
        """Verifica que el backend esté disponible.

        Returns:
            Diccionario con claves ``status`` ("ok" | "error"), ``provider``,
            ``model`` y opcionalmente ``detail`` con el mensaje de error.
        """
