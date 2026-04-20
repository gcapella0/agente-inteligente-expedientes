"""Tests para la API Fase 3 — búsqueda, exportación y cursor pagination (todo mockeado)."""
from __future__ import annotations

import sys
from base64 import b64encode
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app, raise_server_exceptions=True)

# ---------------------------------------------------------------------------
# Datos de prueba
# ---------------------------------------------------------------------------

_CEDULA = "12345678"
_OID = ObjectId()
_OID2 = ObjectId()

_DOCENTE_DOC = {
    "_id": _OID,
    "expediente_numero": "EXP-2026-000001",
    "status": "activo",
    "docente": {
        "cedula": _CEDULA,
        "nombres": "Juan",
        "apellidos": "Pérez",
        "fecha_nacimiento": None,
    },
    "vinculacion_institucional": {"departamento": "Informática", "sede": "Caracas"},
    "formacion_academica": [],
    "completitud": {"porcentaje": 50, "documentos_ids": []},
    "created_at": None,
    "updated_at": None,
}

_DOCUMENTO_DOC = {
    "_id": _OID2,
    "tipo": "cedula_identidad",
    "docente_cedula": _CEDULA,
    "nombre": "cedula_12345678.pdf",
    "validacion": {"estado": "aprobado"},
    "ocr": {
        "procesado": True,
        "confianza_promedio": 0.95,
        "texto_completo": "REPÚBLICA BOLIVARIANA DE VENEZUELA",
        "campos_extraidos": {"numero": "12345678"},
    },
    "created_at": None,
    "updated_at": None,
}


# ---------------------------------------------------------------------------
# TestBusquedaTexto
# ---------------------------------------------------------------------------


class TestBusquedaTexto:
    def _mock_mongo(self, resultados=None, total=0):
        mongo = MagicMock()
        docs = resultados or []
        find_mock = MagicMock()
        find_mock.sort.return_value = find_mock
        find_mock.skip.return_value = find_mock
        find_mock.limit.return_value = iter(docs)
        mongo.documentos.find.return_value = find_mock
        mongo.documentos.count_documents.return_value = total
        mongo.docentes.find_one.return_value = None
        return mongo

    def test_q_demasiado_corto(self):
        r = client.get("/expedientes/buscar-texto?q=a")
        assert r.status_code == 422

    def test_busqueda_sin_resultados(self):
        mongo = self._mock_mongo(resultados=[], total=0)
        with patch("src.api.routers.busqueda.MongoService", return_value=mongo):
            r = client.get("/expedientes/buscar-texto?q=universidad")
        assert r.status_code == 200
        data = r.json()
        assert data["query"] == "universidad"
        assert data["resultados"] == []
        assert data["total"] == 0
        assert "tiempo_busqueda_ms" in data

    def test_busqueda_con_resultado(self):
        doc = dict(_DOCUMENTO_DOC)
        doc["score"] = 1.5
        mongo = self._mock_mongo(resultados=[doc], total=1)
        # Simular nombre del docente
        mongo.docentes.find_one.return_value = {
            "docente": {"nombres": "Juan", "apellidos": "Pérez"}
        }
        with patch("src.api.routers.busqueda.MongoService", return_value=mongo):
            r = client.get("/expedientes/buscar-texto?q=venezuela&limit=10")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert len(data["resultados"]) == 1
        item = data["resultados"][0]
        assert item["tipo"] == "cedula_identidad"
        assert item["relevancia"] == 1.5
        assert item["docente_nombre"] == "Juan Pérez"

    def test_busqueda_con_filtro_tipo(self):
        mongo = self._mock_mongo(resultados=[], total=0)
        with patch("src.api.routers.busqueda.MongoService", return_value=mongo):
            r = client.get("/expedientes/buscar-texto?q=universidad&tipo=titulo_universitario")
        assert r.status_code == 200
        # Verificar que el filtro de tipo fue construido
        call_args = mongo.documentos.find.call_args
        filtro = call_args[0][0]
        assert filtro.get("tipo") == "titulo_universitario"

    def test_busqueda_campos_especificos(self):
        doc = dict(_DOCUMENTO_DOC)
        doc["score"] = 1.0
        mongo = self._mock_mongo(resultados=[doc], total=1)
        with patch("src.api.routers.busqueda.MongoService", return_value=mongo):
            r = client.get("/expedientes/buscar-texto?q=venezuela&campos=numero")
        assert r.status_code == 200
        item = r.json()["resultados"][0]
        assert item.get("numero") == "12345678"

    def test_skip_y_limit(self):
        mongo = self._mock_mongo(resultados=[], total=0)
        with patch("src.api.routers.busqueda.MongoService", return_value=mongo):
            r = client.get("/expedientes/buscar-texto?q=test&skip=10&limit=5")
        assert r.status_code == 200
        data = r.json()
        assert data["skip"] == 10
        assert data["limit"] == 5


# ---------------------------------------------------------------------------
# TestExportacion
# ---------------------------------------------------------------------------


class TestExportacion:
    def _mock_mongo_no_docente(self):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = None
        return mongo

    def _mock_mongo_con_docente(self, documentos=None):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = dict(_DOCENTE_DOC)
        mongo.documentos.find.return_value = iter(documentos or [])
        return mongo

    def test_docente_no_encontrado(self):
        mongo = self._mock_mongo_no_docente()
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/999999/exportar?formato=json")
        assert r.status_code == 404

    def test_exportar_json(self):
        doc = dict(_DOCUMENTO_DOC)
        mongo = self._mock_mongo_con_docente(documentos=[doc])
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        assert f"expediente_{_CEDULA}.json" in r.headers["content-disposition"]
        data = r.json()
        assert data["docente"]["cedula"] == _CEDULA
        assert "documentos" in data

    def test_exportar_json_sin_ocr_por_defecto(self):
        doc = dict(_DOCUMENTO_DOC)
        mongo = self._mock_mongo_con_docente(documentos=[doc])
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=json")
        data = r.json()
        # texto_completo no debe aparecer cuando incluir_ocr=False
        assert "texto_completo" not in data["documentos"][0]["ocr"]

    def test_exportar_json_con_ocr(self):
        doc = dict(_DOCUMENTO_DOC)
        mongo = self._mock_mongo_con_docente(documentos=[doc])
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=json&incluir_ocr=true")
        data = r.json()
        assert data["documentos"][0]["ocr"]["texto_completo"] == "REPÚBLICA BOLIVARIANA DE VENEZUELA"

    def test_exportar_xml(self):
        mongo = self._mock_mongo_con_docente()
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=xml")
        assert r.status_code == 200
        assert "application/xml" in r.headers["content-type"]
        assert f"expediente_{_CEDULA}.xml" in r.headers["content-disposition"]
        assert b"<?xml" in r.content
        assert b"<expediente>" in r.content

    def test_exportar_csv(self):
        mongo = self._mock_mongo_con_docente()
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert b"campo,valor" in r.content

    def test_exportar_formato_invalido(self):
        mongo = self._mock_mongo_con_docente()
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=pdf")
        assert r.status_code == 415

    def test_exportar_sin_documentos(self):
        mongo = self._mock_mongo_con_docente(documentos=[])
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=json&incluir_documentos=true")
        data = r.json()
        assert data["documentos"] == []

    def test_exportar_sin_incluir_documentos(self):
        mongo = self._mock_mongo_con_docente()
        with patch("src.api.routers.exportacion.MongoService", return_value=mongo):
            r = client.get(f"/expedientes/{_CEDULA}/exportar?formato=json&incluir_documentos=false")
        data = r.json()
        assert "documentos" not in data


# ---------------------------------------------------------------------------
# TestCursorPaginacion — /docentes
# ---------------------------------------------------------------------------


class TestCursorPaginacionDocentes:
    def _mock_mongo(self, docs=None, total=0):
        mongo = MagicMock()
        find_mock = MagicMock()
        find_mock.sort.return_value = find_mock
        find_mock.skip.return_value = find_mock
        find_mock.limit.return_value = iter(docs or [])
        mongo.docentes.find.return_value = find_mock
        mongo.docentes.count_documents.return_value = total
        return mongo

    def test_sin_cursor_tiene_mas_false(self):
        doc = dict(_DOCENTE_DOC)
        mongo = self._mock_mongo(docs=[doc], total=1)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/docentes?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert "cursor_siguiente" in data
        assert "tiene_mas" in data
        assert data["tiene_mas"] is False
        assert data["cursor_siguiente"] is None

    def test_tiene_mas_true_cuando_hay_mas(self):
        # Devolver limit+1 docs para simular que hay más
        docs = [dict(_DOCENTE_DOC) for _ in range(3)]
        mongo = self._mock_mongo(docs=docs, total=10)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/docentes?limit=2")
        assert r.status_code == 200
        data = r.json()
        assert data["tiene_mas"] is True
        assert data["cursor_siguiente"] is not None
        assert len(data["items"]) == 2  # recortado al límite

    def test_cursor_invalido_retorna_422(self):
        with patch("src.api.routers.expedientes.MongoService"):
            r = client.get("/docentes?cursor=no-es-base64-valido")
        assert r.status_code == 422

    def test_cursor_valido_aplica_filtro(self):
        oid = ObjectId()
        cursor = b64encode(str(oid).encode()).decode()
        mongo = self._mock_mongo(docs=[], total=0)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/docentes?cursor={cursor}")
        assert r.status_code == 200
        # Verificar que se aplicó filtro _id > cursor_id
        call_args = mongo.docentes.find.call_args
        filtro = call_args[0][0]
        assert "_id" in filtro


# ---------------------------------------------------------------------------
# TestCursorPaginacionBuscar
# ---------------------------------------------------------------------------


class TestCursorPaginacionBuscar:
    def _mock_mongo(self, docs=None, total=0):
        mongo = MagicMock()
        find_mock = MagicMock()
        find_mock.sort.return_value = find_mock
        find_mock.skip.return_value = find_mock
        find_mock.limit.return_value = iter(docs or [])
        mongo.docentes.find.return_value = find_mock
        mongo.docentes.count_documents.return_value = total
        return mongo

    def test_buscar_con_cursor(self):
        oid = ObjectId()
        cursor = b64encode(str(oid).encode()).decode()
        mongo = self._mock_mongo(docs=[], total=0)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/docentes/buscar?cursor={cursor}")
        assert r.status_code == 200

    def test_buscar_cursor_invalido(self):
        with patch("src.api.routers.expedientes.MongoService"):
            r = client.get("/docentes/buscar?cursor=!!!invalido!!!")
        assert r.status_code == 422

    def test_buscar_respuesta_incluye_campos_cursor(self):
        mongo = self._mock_mongo(docs=[], total=0)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/docentes/buscar?q=Juan")
        assert r.status_code == 200
        data = r.json()
        assert "cursor_siguiente" in data
        assert "tiene_mas" in data
