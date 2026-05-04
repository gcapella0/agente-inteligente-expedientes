"""Tests para GET/PUT /config/agentes — sin MongoDB real (todo mockeado)."""
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

_CONFIG_VALIDA = {
    "watcher": {"timeout_segundos": 60, "retry_veces": 3},
    "ocr": {"timeout_segundos": 120, "retry_veces": 2},
    "classifier": {"temperatura": 0.7, "max_tokens": 2000},
    "storage": {"timeout_segundos": 30},
}


def _make_mongo(doc=None):
    mongo = MagicMock()
    mongo.db.__getitem__.return_value.find_one.return_value = doc
    return mongo


class TestGetConfigAgentes:
    def test_sin_jwt_retorna_no_autorizado(self):
        r = client.get("/config/agentes")
        assert r.status_code in (401, 422)

    def test_token_invalido_retorna_401(self):
        r = client.get("/config/agentes", headers={"Authorization": "Bearer token.invalido"})
        assert r.status_code == 401

    def test_con_jwt_valido_retorna_200(self):
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(None)
            r = client.get("/config/agentes", headers=_AUTH)
        assert r.status_code == 200

    def test_retorna_4_agentes(self):
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(None)
            r = client.get("/config/agentes", headers=_AUTH)
        data = r.json()
        assert "watcher" in data
        assert "ocr" in data
        assert "classifier" in data
        assert "storage" in data

    def test_defaults_cuando_no_existe_en_mongo(self):
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(None)
            r = client.get("/config/agentes", headers=_AUTH)
        data = r.json()
        assert data["watcher"]["timeout_segundos"] == 60
        assert data["watcher"]["retry_veces"] == 3
        assert data["ocr"]["timeout_segundos"] == 120
        assert data["classifier"]["temperatura"] == 0.7
        assert data["classifier"]["max_tokens"] == 2000
        assert data["storage"]["timeout_segundos"] == 30

    def test_retorna_config_guardada_en_mongo(self):
        doc_guardado = {
            "_id": "agentes_config",
            "watcher": {"timeout_segundos": 90, "retry_veces": 5},
            "ocr": {"timeout_segundos": 200, "retry_veces": 4},
            "classifier": {"temperatura": 0.3, "max_tokens": 1000},
            "storage": {"timeout_segundos": 60},
            "updated_at": "2026-04-21T00:00:00Z",
        }
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(doc_guardado)
            r = client.get("/config/agentes", headers=_AUTH)
        data = r.json()
        assert data["watcher"]["timeout_segundos"] == 90
        assert data["classifier"]["temperatura"] == 0.3

    def test_response_no_incluye_id_ni_updated_at(self):
        doc_guardado = {
            "_id": "agentes_config",
            **_CONFIG_VALIDA,
            "updated_at": "2026-04-21T00:00:00Z",
        }
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(doc_guardado)
            r = client.get("/config/agentes", headers=_AUTH)
        data = r.json()
        assert "_id" not in data
        assert "updated_at" not in data


class TestPutConfigAgentes:
    def test_sin_jwt_retorna_no_autorizado(self):
        r = client.put("/config/agentes", json=_CONFIG_VALIDA)
        assert r.status_code in (401, 422)

    def test_token_invalido_retorna_401(self):
        r = client.put(
            "/config/agentes",
            json=_CONFIG_VALIDA,
            headers={"Authorization": "Bearer token.invalido"},
        )
        assert r.status_code == 401

    def test_con_jwt_y_body_valido_retorna_200(self):
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(None)
            r = client.put("/config/agentes", json=_CONFIG_VALIDA, headers=_AUTH)
        assert r.status_code == 200

    def test_response_tiene_message(self):
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(None)
            r = client.put("/config/agentes", json=_CONFIG_VALIDA, headers=_AUTH)
        assert r.json()["message"] == "Configuración guardada"

    def test_body_invalido_retorna_422(self):
        body_malo = {"watcher": {"timeout_segundos": "no_es_int"}}
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mock_cls.return_value = _make_mongo(None)
            r = client.put("/config/agentes", json=body_malo, headers=_AUTH)
        assert r.status_code == 422

    def test_llama_update_one_con_upsert(self):
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mongo = _make_mongo(None)
            mock_cls.return_value = mongo
            client.put("/config/agentes", json=_CONFIG_VALIDA, headers=_AUTH)

        col = mongo.db.__getitem__.return_value
        col.update_one.assert_called_once()
        args, kwargs = col.update_one.call_args
        assert args[0] == {"_id": "agentes_config"}
        assert kwargs.get("upsert") is True

    def test_guarda_valores_correctos(self):
        config_nueva = {
            "watcher": {"timeout_segundos": 45, "retry_veces": 1},
            "ocr": {"timeout_segundos": 90, "retry_veces": 1},
            "classifier": {"temperatura": 0.5, "max_tokens": 500},
            "storage": {"timeout_segundos": 15},
        }
        with patch("src.api.routers.config_agentes.MongoService") as mock_cls:
            mongo = _make_mongo(None)
            mock_cls.return_value = mongo
            client.put("/config/agentes", json=config_nueva, headers=_AUTH)

        col = mongo.db.__getitem__.return_value
        _, kwargs = col.update_one.call_args
        set_doc = col.update_one.call_args[0][1]["$set"]
        assert set_doc["watcher"]["timeout_segundos"] == 45
        assert set_doc["classifier"]["temperatura"] == 0.5
