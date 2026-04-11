"""Tests para la capa de proveedores LLM (OpenRouterProvider, OllamaProvider, factory)."""

from __future__ import annotations

import json as json_module
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.llm.abstract_llm_provider import BaseLlmProvider
from src.services.llm.llm_factory import create_llm_provider
from src.services.llm.ollama_provider import OllamaProvider
from src.services.llm.openrouter_provider import OpenRouterProvider
from src.services.llm_service import LlmService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LLM_RESPONSE_VALIDO = {
    "valido": True,
    "tipo": "titulo_universitario",
    "razon_rechazo": None,
    "campos_extraidos": {"nombre_titular": "Ana Pérez", "cedula_titular": "V-11111111"},
    "confianza_clasificacion": 0.95,
}

LLM_RESPONSE_NO_VALIDO = {
    "valido": False,
    "tipo": "no_valido",
    "razon_rechazo": "Documento no relacionado con el expediente docente",
    "campos_extraidos": {},
    "confianza_clasificacion": 0.5,
}


def _openrouter_completion(content: str, tokens: int = 100):
    """Simula una respuesta de la API de OpenRouter."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.total_tokens = tokens
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _ollama_response(content: str, status_code: int = 200):
    """Simula una respuesta HTTP de Ollama (/api/chat)."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.content = content.encode()
    resp.json.return_value = {"message": {"content": content}}
    resp.raise_for_status = MagicMock()
    return resp


# ===========================================================================
# Tests para BaseLlmProvider (interfaz)
# ===========================================================================


class TestBaseLlmProvider:
    """Verifica que BaseLlmProvider es abstracta y no instanciable."""

    def test_no_instanciable_directamente(self):
        with pytest.raises(TypeError):
            BaseLlmProvider()  # type: ignore[abstract]

    def test_subclase_concreta_cumple_contrato(self):
        """Una subclase que implementa todos los métodos es válida."""

        class FakeProvider(BaseLlmProvider):
            @property
            def provider_name(self) -> str:
                return "fake"

            @property
            def model_name(self) -> str:
                return "fake-model"

            def classify_and_extract(self, texto_ocr: str) -> dict:
                return {}

            def health_check(self) -> dict:
                return {"status": "ok"}

        p = FakeProvider()
        assert p.provider_name == "fake"
        assert p.model_name == "fake-model"


# ===========================================================================
# Tests para OpenRouterProvider
# ===========================================================================


class TestOpenRouterProvider:
    """Tests de OpenRouterProvider con cliente OpenAI mockeado."""

    @pytest.fixture
    def provider(self, monkeypatch):
        """OpenRouterProvider con __init__ mockeado."""
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_MODEL", "test-model")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_BASE_URL", "https://fake.api")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_API_KEY", "sk-fake")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_FALLBACK_MODELS", [])

        with patch("src.services.llm.openrouter_provider.OpenAI"):
            p = OpenRouterProvider()
        p.client = MagicMock()
        return p

    def test_provider_name(self, provider):
        assert provider.provider_name == "openrouter"

    def test_model_name(self, provider):
        assert provider.model_name == "test-model"

    def test_classify_and_extract_exitoso(self, provider):
        content = json_module.dumps(LLM_RESPONSE_VALIDO)
        provider.client.chat.completions.create.return_value = _openrouter_completion(content, 80)

        resultado = provider.classify_and_extract("texto ocr de prueba")

        assert resultado["valido"] is True
        assert resultado["tipo"] == "titulo_universitario"
        assert resultado["modelo_llm"] == "test-model"
        assert resultado["tokens_usados"] == 80
        assert resultado["provider"] == "openrouter"
        assert "latencia_ms" in resultado

    def test_classify_and_extract_json_con_markdown(self, provider):
        raw = f"```json\n{json_module.dumps(LLM_RESPONSE_VALIDO)}\n```"
        provider.client.chat.completions.create.return_value = _openrouter_completion(raw)

        resultado = provider.classify_and_extract("texto")
        assert resultado["valido"] is True

    def test_classify_and_extract_fallo_total_retorna_error(self, provider):
        provider.client.chat.completions.create.return_value = _openrouter_completion("no es json")

        resultado = provider.classify_and_extract("texto")

        assert resultado["valido"] is False
        assert resultado["provider"] == "openrouter"
        assert "parsear" in resultado["razon_rechazo"]

    def test_health_check_ok(self, provider):
        provider.client.models.list.return_value = []
        resultado = provider.health_check()

        assert resultado["status"] == "ok"
        assert resultado["provider"] == "openrouter"
        assert resultado["model"] == "test-model"

    def test_health_check_error_conexion(self, provider):
        from openai import APIConnectionError
        provider.client.models.list.side_effect = APIConnectionError(request=MagicMock())

        resultado = provider.health_check()

        assert resultado["status"] == "error"
        assert "detail" in resultado


# ===========================================================================
# Tests para OllamaProvider
# ===========================================================================


class TestOllamaProvider:
    """Tests de OllamaProvider con requests mockeado."""

    @pytest.fixture
    def provider(self, monkeypatch):
        """OllamaProvider con configuración de prueba."""
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_MODEL", "mistral")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_TIMEOUT_SECONDS", 30)
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_NUM_PREDICT", 200)
        return OllamaProvider()

    def test_provider_name(self, provider):
        assert provider.provider_name == "ollama"

    def test_model_name(self, provider):
        assert provider.model_name == "mistral"

    def test_classify_and_extract_exitoso(self, provider):
        content = json_module.dumps(LLM_RESPONSE_VALIDO)
        with patch("requests.post", return_value=_ollama_response(content)):
            resultado = provider.classify_and_extract("texto ocr")

        assert resultado["valido"] is True
        assert resultado["tipo"] == "titulo_universitario"
        assert resultado["modelo_llm"] == "mistral"
        assert resultado["tokens_usados"] is None  # Ollama no reporta tokens
        assert resultado["provider"] == "ollama"
        assert "latencia_ms" in resultado

    def test_classify_and_extract_reintenta_json_invalido(self, provider):
        """Primera respuesta inválida → reintenta → éxito en segundo intento."""
        content_valido = json_module.dumps(LLM_RESPONSE_VALIDO)
        respuestas = [
            _ollama_response("esto no es json"),
            _ollama_response(content_valido),
        ]
        with patch("requests.post", side_effect=respuestas):
            resultado = provider.classify_and_extract("texto")

        assert resultado["valido"] is True

    def test_classify_and_extract_fallo_total(self, provider):
        """Dos respuestas inválidas → retorna error."""
        with patch("requests.post", return_value=_ollama_response("basura")):
            resultado = provider.classify_and_extract("texto")

        assert resultado["valido"] is False
        assert resultado["provider"] == "ollama"
        assert resultado["tokens_usados"] is None

    def test_classify_and_extract_timeout(self, provider):
        with patch("requests.post", side_effect=requests.exceptions.Timeout):
            resultado = provider.classify_and_extract("texto")

        assert resultado["valido"] is False
        assert resultado["provider"] == "ollama"

    def test_classify_and_extract_connection_error(self, provider):
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError):
            resultado = provider.classify_and_extract("texto")

        assert resultado["valido"] is False

    def test_health_check_ok(self, provider):
        tags_resp = MagicMock(spec=requests.Response)
        tags_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=tags_resp):
            resultado = provider.health_check()

        assert resultado["status"] == "ok"
        assert resultado["provider"] == "ollama"
        assert resultado["model"] == "mistral"

    def test_health_check_ollama_no_disponible(self, provider):
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError):
            resultado = provider.health_check()

        assert resultado["status"] == "error"
        assert "detail" in resultado
        assert "localhost" in resultado["detail"]

    def test_health_check_timeout(self, provider):
        with patch("requests.get", side_effect=requests.exceptions.Timeout):
            resultado = provider.health_check()

        assert resultado["status"] == "error"
        assert "Timeout" in resultado["detail"]

    def test_prompt_se_trunca_si_es_largo(self, provider):
        """El texto OCR enviado al user message no supera el límite de caracteres."""
        texto_largo = "x" * 10_000
        payloads: list = []

        def fake_post(url, json=None, timeout=None, **kwargs):
            payloads.append(json)
            return _ollama_response(json_module.dumps(LLM_RESPONSE_VALIDO))

        with patch("requests.post", side_effect=fake_post):
            provider.classify_and_extract(texto_largo)

        assert len(payloads) == 1
        from src.services.llm.ollama_provider import _PROMPT_MAX_CHARS
        # El payload usa /api/chat: messages[1] es el user message
        mensajes = payloads[0]["messages"]
        user_content = mensajes[1]["content"]
        assert texto_largo[:_PROMPT_MAX_CHARS] in user_content
        assert "x" * (_PROMPT_MAX_CHARS + 1) not in user_content


# ===========================================================================
# Tests para create_llm_provider (factory)
# ===========================================================================


class TestCreateLlmProvider:
    """Tests de la factory de proveedores."""

    def test_openrouter_devuelve_instancia_correcta(self, monkeypatch):
        monkeypatch.setattr("src.services.llm.llm_factory.config.LLM_PROVIDER", "openrouter")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_MODEL", "m")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_BASE_URL", "https://x")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_API_KEY", "k")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_FALLBACK_MODELS", [])

        with patch("src.services.llm.openrouter_provider.OpenAI"):
            p = create_llm_provider()

        assert isinstance(p, OpenRouterProvider)
        assert p.provider_name == "openrouter"

    def test_ollama_devuelve_instancia_correcta(self, monkeypatch):
        monkeypatch.setattr("src.services.llm.llm_factory.config.LLM_PROVIDER", "ollama")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_MODEL", "mistral")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_TIMEOUT_SECONDS", 120)
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_NUM_PREDICT", 1000)

        p = create_llm_provider()

        assert isinstance(p, OllamaProvider)
        assert p.provider_name == "ollama"

    def test_proveedor_invalido_lanza_valueerror(self, monkeypatch):
        monkeypatch.setattr("src.services.llm.llm_factory.config.LLM_PROVIDER", "inexistente")

        with pytest.raises(ValueError, match="inexistente"):
            create_llm_provider()

    def test_proveedor_mayusculas_normalizado(self, monkeypatch):
        """El valor de LLM_PROVIDER es case-insensitive."""
        monkeypatch.setattr("src.services.llm.llm_factory.config.LLM_PROVIDER", "OLLAMA")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_MODEL", "mistral")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_TIMEOUT_SECONDS", 120)
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_NUM_PREDICT", 1000)

        p = create_llm_provider()
        assert isinstance(p, OllamaProvider)


# ===========================================================================
# Tests para LlmService con provider inyectado
# ===========================================================================


class TestLlmServiceConProvider:
    """Verifica que LlmService delega correctamente al provider inyectado."""

    @pytest.fixture
    def fake_provider(self):
        """Provider falso que implementa BaseLlmProvider."""

        class FakeProvider(BaseLlmProvider):
            def __init__(self):
                self._calls: list[str] = []
                self._response = {**LLM_RESPONSE_VALIDO, "modelo_llm": "fake/model", "tokens_usados": 42}

            @property
            def provider_name(self) -> str:
                return "fake"

            @property
            def model_name(self) -> str:
                return "fake/model"

            def classify_and_extract(self, texto_ocr: str) -> dict:
                self._calls.append(texto_ocr)
                return self._response

            def health_check(self) -> dict:
                return {"status": "ok", "provider": "fake", "model": "fake/model"}

        return FakeProvider()

    def test_llm_service_delega_classify(self, fake_provider):
        service = LlmService(provider=fake_provider)

        resultado = service.classify_and_extract("texto de prueba")

        assert resultado["valido"] is True
        assert resultado["modelo_llm"] == "fake/model"
        assert "texto de prueba" in fake_provider._calls

    def test_llm_service_expone_model_del_provider(self, fake_provider):
        service = LlmService(provider=fake_provider)
        assert service.model == "fake/model"

    def test_llm_service_health_check_delega(self, fake_provider):
        service = LlmService(provider=fake_provider)
        resultado = service.health_check()

        assert resultado["status"] == "ok"
        assert resultado["provider"] == "fake"

    def test_llm_service_agnostico_openrouter(self, monkeypatch):
        """LlmService con OpenRouterProvider funciona igual que el modo legado."""
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_MODEL", "m")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_BASE_URL", "https://x")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_API_KEY", "k")
        monkeypatch.setattr("src.services.llm.openrouter_provider.config.OPENROUTER_FALLBACK_MODELS", [])

        with patch("src.services.llm.openrouter_provider.OpenAI"):
            provider = OpenRouterProvider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = _openrouter_completion(
            json_module.dumps(LLM_RESPONSE_VALIDO)
        )

        service = LlmService(provider=provider)
        resultado = service.classify_and_extract("texto")

        assert resultado["valido"] is True
        assert resultado["provider"] == "openrouter"

    def test_llm_service_agnostico_ollama(self, monkeypatch):
        """LlmService con OllamaProvider funciona transparentemente."""
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_MODEL", "mistral")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_TIMEOUT_SECONDS", 30)
        monkeypatch.setattr("src.services.llm.ollama_provider.config.OLLAMA_NUM_PREDICT", 200)

        provider = OllamaProvider()
        with patch("requests.post", return_value=_ollama_response(json_module.dumps(LLM_RESPONSE_VALIDO))):
            service = LlmService(provider=provider)
            resultado = service.classify_and_extract("texto")

        assert resultado["valido"] is True
        assert resultado["provider"] == "ollama"

    def test_llm_service_sin_provider_usa_modo_legado(self, monkeypatch):
        """LlmService() sin argumentos sigue usando OpenRouter directo."""
        monkeypatch.setattr("src.services.llm_service.config.OPENROUTER_MODEL", "legacy-model")
        monkeypatch.setattr("src.services.llm_service.config.OPENROUTER_BASE_URL", "https://x")
        monkeypatch.setattr("src.services.llm_service.config.OPENROUTER_API_KEY", "k")
        monkeypatch.setattr("src.services.llm_service.config.OPENROUTER_FALLBACK_MODELS", [])

        with patch("src.services.llm_service.OpenAI"):
            service = LlmService()

        assert service._delegate is None
        assert service.model == "legacy-model"
        assert service.client is not None
