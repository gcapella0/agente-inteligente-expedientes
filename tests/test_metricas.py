"""Tests para GET /metricas — sin MongoDB real (todo mockeado)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.security import create_access_token

client = TestClient(app, raise_server_exceptions=True)

_TOKEN = create_access_token("admin@uneg.edu.ve", "admin")
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _make_mongo(
    total_docs=42,
    completitud_promedio=75.5,
    docentes_aptos=28,
    docentes_totales=35,
):
    mongo = MagicMock()
    mongo.documentos.count_documents.return_value = total_docs

    agg_result = [{"_id": None, "promedio": completitud_promedio}]
    mongo.docentes.aggregate.return_value = iter(agg_result)

    def count_side_effect(filtro):
        if filtro.get("completitud.porcentaje"):
            return docentes_aptos
        return docentes_totales

    mongo.docentes.count_documents.side_effect = count_side_effect
    return mongo


class TestGetMetricas:
    def test_sin_jwt_retorna_no_autorizado(self):
        # Sin header → 422 (campo requerido faltante en FastAPI)
        r = client.get("/metricas/")
        assert r.status_code in (401, 422)

    def test_token_invalido_retorna_401(self):
        r = client.get("/metricas/", headers={"Authorization": "Bearer token.invalido"})
        assert r.status_code == 401

    def test_con_jwt_valido_retorna_200(self):
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo()
            r = client.get("/metricas/", headers=_AUTH)
        assert r.status_code == 200

    def test_response_tiene_4_campos(self):
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo()
            r = client.get("/metricas/", headers=_AUTH)
        data = r.json()
        assert "totalDocumentos" in data
        assert "completitudPromedio" in data
        assert "docentesAptos" in data
        assert "docentesTotales" in data

    def test_total_documentos_es_numero(self):
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(total_docs=42)
            r = client.get("/metricas/", headers=_AUTH)
        assert isinstance(r.json()["totalDocumentos"], int)
        assert r.json()["totalDocumentos"] == 42

    def test_completitud_promedio_es_float(self):
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(completitud_promedio=75.5)
            r = client.get("/metricas/", headers=_AUTH)
        data = r.json()
        assert isinstance(data["completitudPromedio"], (int, float))
        assert 0 <= data["completitudPromedio"] <= 100

    def test_docentes_aptos_es_numero(self):
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(docentes_aptos=28)
            r = client.get("/metricas/", headers=_AUTH)
        assert isinstance(r.json()["docentesAptos"], int)
        assert r.json()["docentesAptos"] == 28

    def test_docentes_totales_es_numero(self):
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(docentes_totales=35)
            r = client.get("/metricas/", headers=_AUTH)
        assert isinstance(r.json()["docentesTotales"], int)
        assert r.json()["docentesTotales"] == 35

    def test_sin_docentes_completitud_promedio_es_cero(self):
        mongo = MagicMock()
        mongo.documentos.count_documents.return_value = 0
        mongo.docentes.aggregate.return_value = iter([])
        mongo.docentes.count_documents.return_value = 0
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = mongo
            r = client.get("/metricas/", headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["completitudPromedio"] == 0.0

    def test_query_documentos_excluye_rechazados(self):
        mongo = _make_mongo()
        with patch("src.api.routers.metricas.MongoService") as mock_cls:
            mock_cls.return_value = mongo
            client.get("/metricas/", headers=_AUTH)
        call_args = mongo.documentos.count_documents.call_args[0][0]
        assert call_args == {"validacion.estado": {"$ne": "rechazado"}}
