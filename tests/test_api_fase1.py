"""Tests para la API Fase 1 — sin MongoDB real (todo mockeado)."""
from __future__ import annotations

import sys
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
# Fixtures y helpers
# ---------------------------------------------------------------------------

_CEDULA = "12345678"
_DOC_OID = ObjectId()
_DOC_ID = str(_DOC_OID)

_DOCENTE_DOC = {
    "_id": ObjectId(),
    "expediente_numero": "EXP-2026-000001",
    "status": "activo",
    "docente": {"cedula": _CEDULA, "nombres": "Juan", "apellidos": "Pérez"},
    "vinculacion_institucional": {"departamento": "Informática", "sede": "Caracas"},
    "completitud": {"porcentaje": 50},
    "updated_at": None,
}

_DOCUMENTO_DOC = {
    "_id": _DOC_OID,
    "tipo": "cedula_identidad",
    "docente_cedula": _CEDULA,
    "validacion": {"estado": "aprobado"},
    "archivo": {"formato": "pdf", "tamano_bytes": 500_000},
    "ocr": {"confianza_promedio": 0.95, "idioma_detectado": "es", "texto_completo": "texto largo..."},
    "created_at": None,
    "updated_at": None,
}


def _mongo_mock(
    docentes_find_one=None,
    docentes_find=None,
    docentes_count=0,
    documentos_find=None,
    documentos_count=0,
    documentos_find_one=None,
):
    """Crea un MongoService mockeado."""
    mongo = MagicMock()
    mongo.docentes.find_one.return_value = docentes_find_one
    mongo.docentes.find.return_value = iter(docentes_find or [])
    mongo.docentes.count_documents.return_value = docentes_count
    mongo.documentos.find.return_value = iter(documentos_find or [])
    mongo.documentos.count_documents.return_value = documentos_count
    mongo.documentos.find_one.return_value = documentos_find_one
    # .find().sort().skip().limit() chain
    find_chain = MagicMock()
    find_chain.sort.return_value = find_chain
    find_chain.skip.return_value = find_chain
    find_chain.limit.return_value = iter(docentes_find or [])
    mongo.docentes.find.return_value = find_chain
    find_chain2 = MagicMock()
    find_chain2.sort.return_value = find_chain2
    find_chain2.skip.return_value = find_chain2
    find_chain2.limit.return_value = iter(documentos_find or [])
    mongo.documentos.find.return_value = find_chain2
    return mongo


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self):
        with patch("src.api.routers.health.MongoService") as mock_cls:
            mock_cls.return_value.client.admin.command.return_value = True
            r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_fallo_mongo(self):
        with patch("src.api.routers.health.MongoService") as mock_cls:
            mock_cls.return_value.client.admin.command.side_effect = Exception("timeout")
            r = client.get("/health")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Root / Info
# ---------------------------------------------------------------------------

class TestRoot:
    def test_root(self):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["app"] == "Expedientes API"

    def test_info(self):
        r = client.get("/info")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data
        assert "endpoints_totales" in data
        assert "documentacion" in data


# ---------------------------------------------------------------------------
# GET /docentes
# ---------------------------------------------------------------------------

class TestListDocentes:
    def test_lista_vacia(self):
        mongo = _mongo_mock(docentes_count=0)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/docentes")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_lista_con_docentes(self):
        doc = dict(_DOCENTE_DOC)
        doc["_id"] = ObjectId()
        mongo = _mongo_mock(docentes_find=[doc], docentes_count=1)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/docentes?limit=5")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert isinstance(data["items"][0]["_id"], str)

    def test_paginacion_parametros(self):
        mongo = _mongo_mock(docentes_count=0)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/docentes?skip=5&limit=20")
        assert r.status_code == 200
        data = r.json()
        assert data["skip"] == 5
        assert data["limit"] == 20


# ---------------------------------------------------------------------------
# GET /docentes/buscar
# ---------------------------------------------------------------------------

class TestBuscarDocentes:
    def _get(self, **params):
        mongo = _mongo_mock(docentes_count=0)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            return client.get("/docentes/buscar", params=params)

    def test_sin_filtros(self):
        r = self._get()
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total_pages" in data

    def test_con_query(self):
        r = self._get(q="García")
        assert r.status_code == 200

    def test_con_filtros_multiples(self):
        r = self._get(departamento="Informática", sede="Caracas", status="activo")
        assert r.status_code == 200

    def test_ordenamiento_aceptado(self):
        for campo in ["apellidos", "cedula", "completitud", "-updated_at"]:
            r = self._get(ordenar=campo)
            assert r.status_code == 200, f"Falló con ordenar={campo}"

    def test_paginacion(self):
        r = self._get(skip=10, limit=5)
        assert r.status_code == 200
        data = r.json()
        assert data["skip"] == 10
        assert data["limit"] == 5


# ---------------------------------------------------------------------------
# GET /expediente/{cedula}
# ---------------------------------------------------------------------------

class TestGetExpediente:
    def test_expediente_existente(self):
        doc = dict(_DOCENTE_DOC)
        doc["_id"] = ObjectId()
        mongo = _mongo_mock(docentes_find_one=doc, documentos_find=[_DOCUMENTO_DOC])
        mongo.documentos.find.return_value = iter([dict(_DOCUMENTO_DOC)])
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/expediente/{_CEDULA}")
        assert r.status_code == 200
        data = r.json()
        assert "docente" in data
        assert "documentos" in data
        assert data["total_documentos"] == 1

    def test_expediente_no_existe(self):
        mongo = _mongo_mock(docentes_find_one=None)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/expediente/99999999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /expediente/{cedula}/documentos
# ---------------------------------------------------------------------------

class TestListarDocumentos:
    def test_docente_no_existe(self):
        mongo = _mongo_mock(docentes_find_one=None)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/expediente/99999999/documentos")
        assert r.status_code == 404

    def test_lista_documentos(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        doc = dict(_DOCUMENTO_DOC)
        mongo = _mongo_mock(docentes_find_one=doc_docente, documentos_count=1)
        mongo.documentos.find.return_value.__iter__ = lambda s: iter([doc])
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/expediente/{_CEDULA}/documentos")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "documentos_incompletos" in data
        assert data["docente_cedula"] == _CEDULA

    def test_ocr_excluido_por_defecto(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        doc = dict(_DOCUMENTO_DOC)
        mongo = _mongo_mock(docentes_find_one=doc_docente, documentos_count=1)
        mongo.documentos.find.return_value.__iter__ = lambda s: iter([doc])
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/expediente/{_CEDULA}/documentos?incluir_ocr=false")
        assert r.status_code == 200
        items = r.json()["items"]
        if items and "ocr" in items[0]:
            assert "texto_completo" not in items[0]["ocr"]

    def test_filtros_tipo_y_validacion(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        mongo = _mongo_mock(docentes_find_one=doc_docente, documentos_count=0)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/expediente/{_CEDULA}/documentos?tipo=cedula_identidad&validacion=aprobado")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /expediente/{cedula}/resumen
# ---------------------------------------------------------------------------

class TestObtenerResumen:
    def test_resumen_json(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        mongo = _mongo_mock(docentes_find_one=doc_docente, documentos_find=[_DOCUMENTO_DOC])
        mongo.documentos.find.return_value = iter([dict(_DOCUMENTO_DOC)])
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/expediente/{_CEDULA}/resumen")
        assert r.status_code == 200
        data = r.json()
        assert "docente_cedula" in data
        assert "documentos_presentes" in data
        assert "documentos_faltantes" in data
        assert "completitud_porcentaje" in data

    def test_resumen_texto(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        mongo = _mongo_mock(docentes_find_one=doc_docente, documentos_find=[])
        mongo.documentos.find.return_value = iter([])
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get(f"/expediente/{_CEDULA}/resumen?formato=texto")
        assert r.status_code == 200
        assert "RESUMEN DE EXPEDIENTE" in r.json()

    def test_resumen_no_existe(self):
        mongo = _mongo_mock(docentes_find_one=None)
        with patch("src.api.routers.expedientes.MongoService", return_value=mongo):
            r = client.get("/expediente/99999999/resumen")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /documentos/{id}
# ---------------------------------------------------------------------------

class TestObtenerDocumento:
    def test_documento_existente(self):
        doc = dict(_DOCUMENTO_DOC)
        mongo = _mongo_mock(documentos_find_one=doc)
        with patch("src.api.routers.documentos.MongoService", return_value=mongo):
            r = client.get(f"/documentos/{_DOC_ID}")
        assert r.status_code == 200
        data = r.json()
        assert data["tipo"] == "cedula_identidad"
        assert isinstance(data["_id"], str)

    def test_documento_no_existe(self):
        mongo = _mongo_mock(documentos_find_one=None)
        with patch("src.api.routers.documentos.MongoService", return_value=mongo):
            r = client.get(f"/documentos/{_DOC_ID}")
        assert r.status_code == 404

    def test_id_invalido(self):
        r = client.get("/documentos/id_invalido_xxx")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /documentos/{id}/validacion
# ---------------------------------------------------------------------------

class TestValidacionDocumento:
    def test_validacion_existente(self):
        doc = dict(_DOCUMENTO_DOC)
        mongo = _mongo_mock(documentos_find_one=doc)
        with patch("src.api.routers.documentos.MongoService", return_value=mongo):
            r = client.get(f"/documentos/{_DOC_ID}/validacion")
        assert r.status_code == 200
        data = r.json()
        assert "validaciones" in data
        assert "es_valido_para_expediente" in data
        assert "formato" in data["validaciones"]

    def test_validacion_no_existe(self):
        mongo = _mongo_mock(documentos_find_one=None)
        with patch("src.api.routers.documentos.MongoService", return_value=mongo):
            r = client.get(f"/documentos/{_DOC_ID}/validacion")
        assert r.status_code == 404

    def test_validacion_id_invalido(self):
        r = client.get("/documentos/invalid_id/validacion")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /config/*
# ---------------------------------------------------------------------------

class TestConfig:
    def test_tipos_documento(self):
        r = client.get("/config/tipos-documento")
        assert r.status_code == 200
        data = r.json()
        assert "tipos_documento" in data
        assert len(data["tipos_documento"]) == 22
        assert data["documentos_requeridos"] == 10

    def test_estados_validacion(self):
        r = client.get("/config/estados-validacion")
        assert r.status_code == 200
        estados = r.json()["estados"]
        ids = {e["id"] for e in estados}
        assert {"pendiente", "aprobado", "rechazado", "requiere_revision"} == ids

    def test_estados_docente(self):
        r = client.get("/config/estados-docente")
        assert r.status_code == 200
        estados = r.json()["estados"]
        ids = {e["id"] for e in estados}
        assert {"activo", "inactivo", "en_revision", "completo", "incompleto"} == ids
