"""Tests para LlmService y ClassifierAgent."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.llm_service import LlmService, _MARKDOWN_FENCE_RE
from src.agents.classifier_agent import ClassifierAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LLM_RESPONSE_VALIDO = {
    "valido": True,
    "tipo": "titulo_universitario",
    "razon_rechazo": None,
    "campos_extraidos": {
        "nombre_titular": "María Elena García",
        "cedula_titular": "V-12345678",
        "institucion_emisora": "Universidad Nacional Experimental de Guayana",
        "titulo_otorgado": "Licenciada en Educación",
        "fecha_emision": "2015-07-15",
    },
    "confianza_clasificacion": 0.92,
}

LLM_RESPONSE_NO_VALIDO = {
    "valido": False,
    "tipo": "no_valido",
    "razon_rechazo": "El documento es una factura comercial",
    "campos_extraidos": {},
    "confianza_clasificacion": 0.85,
}

OCR_RESULT_COMPLETO = {
    "archivo_path": Path("/tmp/test/titulo.pdf"),
    "archivo_nombre": "titulo.pdf",
    "carpeta_origen": "Maria_Elena_Garcia",
    "formato": "pdf",
    "tamano_bytes": 1024,
    "hash_sha256": "abc123",
    "ocr_resultado": {
        "texto_completo": "República Bolivariana de Venezuela Universidad Nacional...",
        "json_export": {},
        "json_ligero": {
            "pages": [
                {
                    "page": 0,
                    "blocks": [
                        {
                            "lines": [
                                "República Bolivariana de Venezuela",
                                "Universidad Nacional Experimental de Guayana",
                                "Licenciada en Educación",
                                "María Elena García V-12345678",
                            ]
                        }
                    ],
                }
            ]
        },
        "confianza_promedio": 0.95,
        "paginas": 1,
        "idioma_detectado": "es",
        "palabras_detectadas": 50,
    },
}

OCR_RESULT_SIN_TEXTO = {
    "archivo_path": Path("/tmp/test/vacio.pdf"),
    "archivo_nombre": "vacio.pdf",
    "carpeta_origen": "Test",
    "formato": "pdf",
    "tamano_bytes": 100,
    "hash_sha256": "def456",
    "ocr_resultado": {
        "texto_completo": "",
        "json_export": {},
        "json_ligero": {"pages": []},
        "confianza_promedio": 0.0,
        "paginas": 0,
        "idioma_detectado": "desconocido",
        "palabras_detectadas": 0,
    },
}

OCR_RESULT_SIN_OCR = {
    "archivo_path": Path("/tmp/test/fallido.pdf"),
    "archivo_nombre": "fallido.pdf",
    "carpeta_origen": "Test",
    "formato": "pdf",
    "tamano_bytes": 100,
    "hash_sha256": "ghi789",
    "ocr_resultado": None,
}


def _build_fake_completion(content: str, total_tokens: int = 150):
    """Construye un objeto simulando la respuesta de OpenAI."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.total_tokens = total_tokens
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _build_fake_completion_no_usage(content: str):
    """Respuesta sin campo usage (algunos modelos no lo reportan)."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    response.usage = None
    return response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_llm_service():
    """Retorna un LlmService con el cliente OpenAI mockeado."""

    def factory(
        response_dict: dict | None = None,
        raw_content: str | None = None,
        total_tokens: int = 150,
        should_fail: bool = False,
        fail_exception: Exception | None = None,
        no_usage: bool = False,
    ) -> LlmService:
        with patch.object(LlmService, "__init__", lambda self: None):
            service = LlmService()
            service.model = "test-model/fake"
            service.client = MagicMock()

        if should_fail:
            exc = fail_exception or Exception("Error simulado")
            service.client.chat.completions.create.side_effect = exc
        else:
            if raw_content is not None:
                content = raw_content
            elif response_dict is not None:
                content = json.dumps(response_dict, ensure_ascii=False)
            else:
                content = json.dumps(LLM_RESPONSE_VALIDO, ensure_ascii=False)

            if no_usage:
                fake_resp = _build_fake_completion_no_usage(content)
            else:
                fake_resp = _build_fake_completion(content, total_tokens)
            service.client.chat.completions.create.return_value = fake_resp

        return service

    return factory


@pytest.fixture
def fake_classifier(fake_llm_service):
    """Retorna un ClassifierAgent con LlmService mockeado."""

    def factory(**kwargs) -> ClassifierAgent:
        service = fake_llm_service(**kwargs)
        return ClassifierAgent(service)

    return factory


# ===========================================================================
# Tests para LlmService._parse_json
# ===========================================================================


class TestParseJson:
    """Tests del parseo de JSON desde respuestas LLM."""

    def test_json_limpio(self):
        text = '{"valido": true, "tipo": "titulo_universitario"}'
        result = LlmService._parse_json(text)
        assert result == {"valido": True, "tipo": "titulo_universitario"}

    def test_json_con_fences_markdown(self):
        text = '```json\n{"valido": true}\n```'
        result = LlmService._parse_json(text)
        assert result == {"valido": True}

    def test_json_con_fences_sin_lang(self):
        text = '```\n{"tipo": "otro"}\n```'
        result = LlmService._parse_json(text)
        assert result == {"tipo": "otro"}

    def test_json_con_espacios_alrededor(self):
        text = '  \n  {"valido": false}  \n  '
        result = LlmService._parse_json(text)
        assert result == {"valido": False}

    def test_texto_no_json_retorna_none(self):
        assert LlmService._parse_json("esto no es json") is None

    def test_json_invalido_retorna_none(self):
        assert LlmService._parse_json('{"incompleto": ') is None

    def test_array_json_retorna_none(self):
        """Solo aceptamos dicts, no arrays."""
        assert LlmService._parse_json('[1, 2, 3]') is None

    def test_string_json_retorna_none(self):
        assert LlmService._parse_json('"solo un string"') is None

    def test_json_complejo_con_fences(self):
        data = LLM_RESPONSE_VALIDO.copy()
        text = f"```json\n{json.dumps(data, ensure_ascii=False)}\n```"
        result = LlmService._parse_json(text)
        assert result["tipo"] == "titulo_universitario"
        assert result["campos_extraidos"]["nombre_titular"] == "María Elena García"

    def test_string_vacia(self):
        assert LlmService._parse_json("") is None

    def test_numero_json_retorna_none(self):
        assert LlmService._parse_json("42") is None


# ===========================================================================
# Tests para LlmService._call_llm
# ===========================================================================


class TestCallLlm:
    """Tests de la llamada al LLM."""

    def test_llamada_exitosa(self, fake_llm_service):
        service = fake_llm_service()
        contenido, tokens, rate_limited = service._call_llm("texto de prueba")
        assert contenido is not None
        assert tokens == 150
        assert rate_limited is False
        service.client.chat.completions.create.assert_called_once()

    def test_parametros_de_llamada(self, fake_llm_service):
        service = fake_llm_service()
        service._call_llm("mi texto ocr")
        call_kwargs = service.client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "test-model/fake"
        assert call_kwargs["max_tokens"] == 1000
        assert call_kwargs["temperature"] == 0.1
        assert len(call_kwargs["messages"]) == 2
        assert call_kwargs["messages"][0]["role"] == "system"
        assert "mi texto ocr" in call_kwargs["messages"][1]["content"]

    def test_error_conexion_retorna_none(self, fake_llm_service):
        from openai import APIConnectionError
        service = fake_llm_service(
            should_fail=True,
            fail_exception=APIConnectionError(request=MagicMock()),
        )
        contenido, tokens, rate_limited = service._call_llm("texto")
        assert contenido is None
        assert tokens == 0
        assert rate_limited is False

    def test_error_timeout_retorna_none(self, fake_llm_service):
        from openai import APITimeoutError
        service = fake_llm_service(
            should_fail=True,
            fail_exception=APITimeoutError(request=MagicMock()),
        )
        contenido, tokens, rate_limited = service._call_llm("texto")
        assert contenido is None
        assert tokens == 0
        assert rate_limited is False

    def test_rate_limit_retorna_flag(self, fake_llm_service):
        from openai import RateLimitError
        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        service = fake_llm_service(
            should_fail=True,
            fail_exception=RateLimitError(
                message="rate limited",
                response=response,
                body=None,
            ),
        )
        contenido, tokens, rate_limited = service._call_llm("texto")
        assert contenido is None
        assert tokens == 0
        assert rate_limited is True

    def test_error_generico_retorna_none(self, fake_llm_service):
        service = fake_llm_service(
            should_fail=True,
            fail_exception=RuntimeError("algo salió mal"),
        )
        contenido, tokens, rate_limited = service._call_llm("texto")
        assert contenido is None
        assert tokens == 0
        assert rate_limited is False

    def test_sin_usage_retorna_cero_tokens(self, fake_llm_service):
        service = fake_llm_service(no_usage=True)
        contenido, tokens, rate_limited = service._call_llm("texto")
        assert contenido is not None
        assert tokens == 0
        assert rate_limited is False

    def test_contenido_none_retorna_string_vacio(self, fake_llm_service):
        """Si el LLM retorna content=None, se convierte a string vacío."""
        with patch.object(LlmService, "__init__", lambda self: None):
            service = LlmService()
            service.model = "test-model/fake"
            service.client = MagicMock()

        choice = MagicMock()
        choice.message.content = None
        response = MagicMock()
        response.choices = [choice]
        response.usage = MagicMock(total_tokens=10)
        service.client.chat.completions.create.return_value = response

        contenido, tokens, rate_limited = service._call_llm("texto")
        assert contenido == ""
        assert tokens == 10
        assert rate_limited is False


# ===========================================================================
# Tests para LlmService.classify_and_extract
# ===========================================================================


class TestClassifyAndExtract:
    """Tests del método principal de clasificación."""

    def test_clasificacion_exitosa(self, fake_llm_service):
        service = fake_llm_service(response_dict=LLM_RESPONSE_VALIDO)
        resultado = service.classify_and_extract("texto ocr")
        assert resultado["valido"] is True
        assert resultado["tipo"] == "titulo_universitario"
        assert resultado["modelo_llm"] == "test-model/fake"
        assert resultado["tokens_usados"] == 150

    def test_documento_no_valido(self, fake_llm_service):
        service = fake_llm_service(response_dict=LLM_RESPONSE_NO_VALIDO)
        resultado = service.classify_and_extract("texto de factura")
        assert resultado["valido"] is False
        assert resultado["tipo"] == "no_valido"
        assert "factura" in resultado["razon_rechazo"]

    def test_reintento_tras_json_invalido(self, fake_llm_service):
        """Si la primera respuesta no es JSON, reintenta una vez."""
        with patch.object(LlmService, "__init__", lambda self: None):
            service = LlmService()
            service.model = "test-model/fake"
            service.client = MagicMock()

        json_valido = json.dumps(LLM_RESPONSE_VALIDO)
        resp_invalida = _build_fake_completion("esto no es json")
        resp_valida = _build_fake_completion(json_valido)
        service.client.chat.completions.create.side_effect = [
            resp_invalida,
            resp_valida,
        ]

        resultado = service.classify_and_extract("texto")
        assert resultado["valido"] is True
        assert service.client.chat.completions.create.call_count == 2

    def test_fallo_total_tras_todos_los_intentos(self, fake_llm_service):
        """Si todos los intentos fallan, retorna dict de error."""
        service = fake_llm_service(raw_content="no json aquí tampoco")
        resp_mal = _build_fake_completion("basura")
        service.client.chat.completions.create.side_effect = [
            resp_mal, resp_mal, resp_mal,
        ]

        resultado = service.classify_and_extract("texto")
        assert resultado["valido"] is False
        assert resultado["tipo"] == "no_valido"
        assert "parsear" in resultado["razon_rechazo"]
        assert resultado["tokens_usados"] == 0

    def test_error_red_todos_los_intentos(self, fake_llm_service):
        """Si todos los intentos fallan por red, retorna error."""
        service = fake_llm_service(
            should_fail=True,
            fail_exception=Exception("sin conexión"),
        )
        resultado = service.classify_and_extract("texto")
        assert resultado["valido"] is False
        assert resultado["tokens_usados"] == 0

    def test_rate_limit_con_backoff_y_recuperacion(self, fake_llm_service):
        """Rate limit espera con backoff y reintenta exitosamente."""
        with patch.object(LlmService, "__init__", lambda self: None):
            service = LlmService()
            service.model = "test-model/fake"
            service.client = MagicMock()

        from openai import RateLimitError
        rate_err = RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        json_valido = json.dumps(LLM_RESPONSE_VALIDO)
        resp_ok = _build_fake_completion(json_valido)
        service.client.chat.completions.create.side_effect = [rate_err, resp_ok]

        with patch("src.services.llm_service.time.sleep") as mock_sleep:
            resultado = service.classify_and_extract("texto")

        assert resultado["valido"] is True
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] >= 10.0  # base delay

    def test_rate_limit_agota_reintentos(self, fake_llm_service):
        """Rate limit que persiste agota todos los reintentos."""
        from openai import RateLimitError
        rate_err = RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        service = fake_llm_service(
            should_fail=True,
            fail_exception=rate_err,
        )

        with patch("src.services.llm_service.time.sleep"):
            resultado = service.classify_and_extract("texto")

        assert resultado["valido"] is False
        assert resultado["tokens_usados"] == 0

    def test_respuesta_con_fences_markdown(self, fake_llm_service):
        """JSON envuelto en markdown fences se parsea correctamente."""
        json_str = json.dumps(LLM_RESPONSE_VALIDO)
        raw = f"```json\n{json_str}\n```"
        service = fake_llm_service(raw_content=raw)
        resultado = service.classify_and_extract("texto")
        assert resultado["valido"] is True
        assert resultado["tipo"] == "titulo_universitario"

    def test_campos_extraidos_preservados(self, fake_llm_service):
        service = fake_llm_service(response_dict=LLM_RESPONSE_VALIDO)
        resultado = service.classify_and_extract("texto")
        campos = resultado["campos_extraidos"]
        assert campos["nombre_titular"] == "María Elena García"
        assert campos["cedula_titular"] == "V-12345678"
        assert campos["institucion_emisora"] == "Universidad Nacional Experimental de Guayana"


# ===========================================================================
# Tests para ClassifierAgent.classify
# ===========================================================================


class TestClassifierAgentClassify:
    """Tests del método classify del ClassifierAgent."""

    def test_clasificacion_documento_valido(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier(response_dict=LLM_RESPONSE_VALIDO)
        resultado = agent.classify(OCR_RESULT_COMPLETO)

        assert "clasificacion" in resultado
        c = resultado["clasificacion"]
        assert c["valido"] is True
        assert c["tipo"] == "titulo_universitario"
        assert c["modelo_llm"] == "test-model/fake"
        assert c["tokens_usados"] == 150
        assert isinstance(c["campos_extraidos"], dict)
        assert c["confianza_clasificacion"] == 0.92

        # Verifica que los datos originales se preservan
        assert resultado["archivo_nombre"] == "titulo.pdf"
        assert resultado["hash_sha256"] == "abc123"

    def test_clasificacion_documento_rechazado(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier(response_dict=LLM_RESPONSE_NO_VALIDO)
        resultado = agent.classify(OCR_RESULT_COMPLETO)

        c = resultado["clasificacion"]
        assert c["valido"] is False
        assert c["tipo"] == "no_valido"
        assert "factura" in c["razon_rechazo"]

    def test_sin_ocr_resultado_retorna_error(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier()
        resultado = agent.classify(OCR_RESULT_SIN_OCR)

        c = resultado["clasificacion"]
        assert c["valido"] is False
        assert "Sin texto OCR" in c["razon_rechazo"]
        assert c["tokens_usados"] == 0

    def test_texto_vacio_retorna_error(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier()
        resultado = agent.classify(OCR_RESULT_SIN_TEXTO)

        c = resultado["clasificacion"]
        assert c["valido"] is False
        assert "Sin texto OCR" in c["razon_rechazo"]

    def test_excepcion_llm_retorna_error(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier()
        agent.llm_service.classify_and_extract = MagicMock(
            side_effect=RuntimeError("LLM explotó")
        )
        resultado = agent.classify(OCR_RESULT_COMPLETO)

        c = resultado["clasificacion"]
        assert c["valido"] is False
        assert "LLM explotó" in c["razon_rechazo"]

    def test_preserva_datos_originales_ocr(self, fake_classifier, monkeypatch):
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log", lambda *a, **kw: None
        )
        agent = fake_classifier()
        resultado = agent.classify(OCR_RESULT_COMPLETO)

        assert resultado["archivo_nombre"] == "titulo.pdf"
        assert resultado["carpeta_origen"] == "Maria_Elena_Garcia"
        assert resultado["formato"] == "pdf"
        assert resultado["tamano_bytes"] == 1024
        assert resultado["hash_sha256"] == "abc123"
        assert resultado["ocr_resultado"] is not None

    def test_archivo_nombre_desconocido_si_falta(self, fake_classifier, monkeypatch):
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log", lambda *a, **kw: None
        )
        agent = fake_classifier()
        resultado = agent.classify({"ocr_resultado": None})

        c = resultado["clasificacion"]
        assert c["valido"] is False

    def test_claves_clasificacion_completas(self, fake_classifier, monkeypatch):
        """Verifica que clasificacion tiene todas las claves esperadas."""
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log", lambda *a, **kw: None
        )
        agent = fake_classifier()
        resultado = agent.classify(OCR_RESULT_COMPLETO)

        claves_esperadas = {
            "valido", "tipo", "campos_extraidos",
            "confianza_clasificacion", "razon_rechazo",
            "modelo_llm", "tokens_usados",
        }
        assert set(resultado["clasificacion"].keys()) == claves_esperadas

    def test_usa_json_ligero_en_vez_de_texto_completo(self, fake_classifier, monkeypatch):
        """Cuando json_ligero está presente, el LLM recibe el JSON serializado."""
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log", lambda *a, **kw: None
        )
        agent = fake_classifier(response_dict=LLM_RESPONSE_VALIDO)
        agent.classify(OCR_RESULT_COMPLETO)

        call_kwargs = agent.llm_service.client.chat.completions.create.call_args[1]
        user_msg = call_kwargs["messages"][1]["content"]
        # json_ligero se serializa y se envía, debe contener la estructura pages
        assert '"pages"' in user_msg
        assert "República Bolivariana de Venezuela" in user_msg

    def test_fallback_a_texto_completo_sin_json_ligero(self, fake_classifier, monkeypatch):
        """Sin json_ligero, el LLM recibe texto_completo como fallback."""
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log", lambda *a, **kw: None
        )
        ocr_sin_ligero = {
            **OCR_RESULT_COMPLETO,
            "ocr_resultado": {
                "texto_completo": "Texto plano del documento",
                "json_export": {},
                "confianza_promedio": 0.9,
                "paginas": 1,
                "idioma_detectado": "es",
                "palabras_detectadas": 5,
            },
        }
        agent = fake_classifier(response_dict=LLM_RESPONSE_VALIDO)
        agent.classify(ocr_sin_ligero)

        call_kwargs = agent.llm_service.client.chat.completions.create.call_args[1]
        user_msg = call_kwargs["messages"][1]["content"]
        assert "Texto plano del documento" in user_msg
        assert '"pages"' not in user_msg


# ===========================================================================
# Tests para audit_log del ClassifierAgent
# ===========================================================================


class TestClassifierAuditLog:
    """Tests de los registros de auditoría del ClassifierAgent."""

    def test_audit_clasificado_ok(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier(response_dict=LLM_RESPONSE_VALIDO)
        agent.classify(OCR_RESULT_COMPLETO)

        assert len(audit_calls) == 1
        args, kwargs = audit_calls[0]
        assert args[0] == "classifier"
        assert args[1] == "clasificado"
        assert args[2] == "ok"
        assert kwargs["documento_tipo"] == "titulo_universitario"
        detalle = json.loads(kwargs["detalle"])
        assert "modelo_llm" in detalle
        assert "confianza_clasificacion" in detalle
        assert "campos_extraidos_count" in detalle
        assert "tokens_usados" in detalle
        assert "tiempo_respuesta_ms" in detalle

    def test_audit_clasificado_rechazado(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier(response_dict=LLM_RESPONSE_NO_VALIDO)
        agent.classify(OCR_RESULT_COMPLETO)

        assert len(audit_calls) == 1
        args, kwargs = audit_calls[0]
        assert args[1] == "clasificado"
        assert args[2] == "rechazado"
        assert kwargs["documento_tipo"] == "no_valido"

    def test_audit_clasificacion_fallida_sin_ocr(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier()
        agent.classify(OCR_RESULT_SIN_OCR)

        assert len(audit_calls) == 1
        args, kwargs = audit_calls[0]
        assert args[1] == "clasificacion_fallida"
        assert args[2] == "error"
        detalle = json.loads(kwargs["detalle"])
        assert detalle["razon"] == "sin_texto_ocr"

    def test_audit_clasificacion_fallida_excepcion(self, fake_classifier, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier()
        agent.llm_service.classify_and_extract = MagicMock(
            side_effect=RuntimeError("boom")
        )
        agent.classify(OCR_RESULT_COMPLETO)

        assert len(audit_calls) == 1
        args, kwargs = audit_calls[0]
        assert args[1] == "clasificacion_fallida"
        assert args[2] == "error"
        detalle = json.loads(kwargs["detalle"])
        assert "boom" in detalle["error"]
        assert "tiempo_respuesta_ms" in detalle

    def test_audit_detalle_campos_count(self, fake_classifier, monkeypatch):
        """El detalle debe incluir la cantidad de campos extraídos."""
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.classifier_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )

        agent = fake_classifier(response_dict=LLM_RESPONSE_VALIDO)
        agent.classify(OCR_RESULT_COMPLETO)

        detalle = json.loads(audit_calls[0][1]["detalle"])
        assert detalle["campos_extraidos_count"] == 5  # 5 campos en LLM_RESPONSE_VALIDO


# ===========================================================================
# Tests para el regex de markdown fences
# ===========================================================================


class TestMarkdownFenceRegex:
    """Tests del regex para limpiar fences markdown."""

    def test_fence_json(self):
        text = '```json\n{"key": "val"}\n```'
        match = _MARKDOWN_FENCE_RE.search(text)
        assert match is not None
        assert '"key"' in match.group(1)

    def test_fence_sin_tipo(self):
        text = '```\n{"key": "val"}\n```'
        match = _MARKDOWN_FENCE_RE.search(text)
        assert match is not None

    def test_sin_fence(self):
        text = '{"key": "val"}'
        match = _MARKDOWN_FENCE_RE.search(text)
        assert match is None

    def test_fence_multilinea(self):
        text = '```json\n{\n  "key": "val",\n  "num": 42\n}\n```'
        match = _MARKDOWN_FENCE_RE.search(text)
        assert match is not None
        inner = match.group(1).strip()
        parsed = json.loads(inner)
        assert parsed["num"] == 42
