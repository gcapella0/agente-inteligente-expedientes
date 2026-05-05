"""Tests para el endpoint POST /expedientes/{cedula}/chat."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.main import app
from src.api.security import create_access_token

client = TestClient(app, raise_server_exceptions=True)

_HEADERS = {"Authorization": f"Bearer {create_access_token('test@test.com', 'admin')}"}
_CEDULA = "12345678"

_DOCENTE_DOC = {
    "_id": ObjectId(),
    "docente": {
        "cedula": _CEDULA,
        "nombres": "Juan",
        "apellidos": "Pérez",
        "contacto": {"email_personal": "juan@test.com", "telefono_principal": "0424-0000000"},
        "nacionalidad": "venezolano",
    },
    "vinculacion_institucional": {
        "departamento": "Ingeniería Informática",
        "sede": "Caracas",
        "cargo_actual": "Profesor Ordinario",
        "categoria": "Asistente",
        "dedicacion": "tiempo_completo",
        "tipo_contratacion": "ordinario",
    },
    "completitud": {
        "porcentaje": 70,
        "documentos_faltantes": ["rif", "cuenta_bancaria"],
        "documentos_ids": [],
    },
    "formacion_academica": [
        {"titulo": "Ingeniero en Sistemas", "institucion": "UCV", "ano_graduacion": "2005"},
    ],
}

_DOC_DOC = {
    "_id": ObjectId(),
    "tipo": "titulo_universitario",
    "docente_cedula": _CEDULA,
    "archivo": {"nombre_original": "titulo.pdf", "formato": "pdf", "tamano_bytes": 102400},
    "ocr": {"texto_completo": "Universidad Central de Venezuela. Título de Ingeniero en Sistemas."},
    "validacion": {"estado": "aprobado"},
}


def _mock_provider(respuesta: str = "El docente tiene 1 documento aprobado.") -> MagicMock:
    """Crea un provider mockeado que retorna la respuesta dada desde chat()."""
    p = MagicMock()
    p.chat.return_value = respuesta
    p.model_name = "openrouter/test-model"
    p.provider_name = "openrouter"
    return p


def _make_mongo(docente=_DOCENTE_DOC, documentos=None):
    """Crea un MongoService mockeado con find_one y find configurados."""
    if documentos is None:
        documentos = [_DOC_DOC]
    mongo = MagicMock()
    mongo.docentes.find_one.return_value = docente
    mongo.documentos.find.return_value.__iter__ = lambda _self: iter(documentos)
    mongo.documentos.find.return_value.limit.return_value = documentos
    mongo.db.__getitem__.return_value.insert_one.return_value = MagicMock()
    return mongo


# ===========================================================================
# Tests
# ===========================================================================


def test_chat_exito():
    """POST con pregunta válida devuelve 200 y la respuesta del LLM."""
    provider = _mock_provider("Tiene 1 documento aprobado.")
    mongo = _make_mongo()

    with patch("src.api.routers.expedientes_chat.MongoService", return_value=mongo), \
         patch("src.api.routers.expedientes_chat.create_llm_provider", return_value=provider):
        r = client.post(
            f"/expedientes/{_CEDULA}/chat",
            json={"pregunta": "¿Cuántos documentos tiene?"},
            headers=_HEADERS,
        )

    assert r.status_code == 200
    body = r.json()
    assert body["exito"] is True
    assert "respuesta" in body
    assert body["cedula"] == _CEDULA
    assert "modelo" in body
    assert isinstance(body["latencia_ms"], int)
    assert body["latencia_ms"] >= 0

    # El provider recibió un user prompt que contiene la pregunta y la cédula
    llamada = provider.chat.call_args
    user_prompt = llamada[0][1]
    assert "¿Cuántos documentos tiene?" in user_prompt
    assert _CEDULA in user_prompt


def test_pregunta_solo_espacios_400():
    """Pregunta compuesta solo de espacios devuelve 400."""
    provider = _mock_provider()
    mongo = _make_mongo()

    with patch("src.api.routers.expedientes_chat.MongoService", return_value=mongo), \
         patch("src.api.routers.expedientes_chat.create_llm_provider", return_value=provider):
        r = client.post(
            f"/expedientes/{_CEDULA}/chat",
            json={"pregunta": "   "},
            headers=_HEADERS,
        )

    assert r.status_code == 400
    assert "vacía" in r.json()["detail"]
    provider.chat.assert_not_called()


def test_pregunta_demasiado_larga_422():
    """Pregunta de más de 500 caracteres devuelve 422 (validación Pydantic)."""
    r = client.post(
        f"/expedientes/{_CEDULA}/chat",
        json={"pregunta": "a" * 501},
        headers=_HEADERS,
    )
    assert r.status_code == 422


def test_docente_no_encontrado_404():
    """Cédula inexistente devuelve 404 sin llamar al LLM."""
    provider = _mock_provider()
    mongo = MagicMock()
    mongo.docentes.find_one.return_value = None

    with patch("src.api.routers.expedientes_chat.MongoService", return_value=mongo), \
         patch("src.api.routers.expedientes_chat.create_llm_provider", return_value=provider):
        r = client.post(
            "/expedientes/99999999/chat",
            json={"pregunta": "¿Quién es este docente?"},
            headers=_HEADERS,
        )

    assert r.status_code == 404
    provider.chat.assert_not_called()


def test_error_llm_503():
    """Cuando el LLM lanza RuntimeError, el endpoint devuelve 503."""
    provider = _mock_provider()
    provider.chat.side_effect = RuntimeError("Ollama timeout tras 120s")
    mongo = _make_mongo()

    with patch("src.api.routers.expedientes_chat.MongoService", return_value=mongo), \
         patch("src.api.routers.expedientes_chat.create_llm_provider", return_value=provider):
        r = client.post(
            f"/expedientes/{_CEDULA}/chat",
            json={"pregunta": "¿Es apto para presentar?"},
            headers=_HEADERS,
        )

    assert r.status_code == 503


def test_create_provider_falla_503():
    """Si create_llm_provider lanza una excepción, el endpoint devuelve 503."""
    mongo = _make_mongo()

    with patch("src.api.routers.expedientes_chat.MongoService", return_value=mongo), \
         patch("src.api.routers.expedientes_chat.create_llm_provider",
               side_effect=RuntimeError("MongoDB no disponible para leer config LLM")):
        r = client.post(
            f"/expedientes/{_CEDULA}/chat",
            json={"pregunta": "¿Qué documentos le faltan?"},
            headers=_HEADERS,
        )

    assert r.status_code == 503
