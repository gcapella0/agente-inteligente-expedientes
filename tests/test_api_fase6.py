"""Tests para la API Fase 6 — agentes, config LLM, logs (todo mockeado)."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from src.api.security import create_access_token

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

_TOKEN_ADMIN = create_access_token("admin@uneg.edu.ve", "admin")
_AUTH_ADMIN = {"Authorization": f"Bearer {_TOKEN_ADMIN}"}

_TOKEN_USER = create_access_token("user@uneg.edu.ve", "usuario")
_AUTH_USER = {"Authorization": f"Bearer {_TOKEN_USER}"}


# ---------------------------------------------------------------------------
# Helpers MongoDB mock
# ---------------------------------------------------------------------------


def _make_mongo_mock_agentes(docs: list[dict] | None = None, pipeline_doc: dict | None = None):
    """Mock de MongoService para la colección sistema_agentes_estado."""
    mongo = MagicMock()
    col = MagicMock()

    all_docs = list(docs or [])
    if pipeline_doc:
        all_docs.append(pipeline_doc)

    col.find.return_value = iter(all_docs)
    col.find_one.return_value = None
    col.update_one.return_value = MagicMock()
    mongo.db.__getitem__ = lambda self, key: col

    return mongo, col


def _make_mongo_mock_config(doc: dict | None = None):
    """Mock de MongoService para sistema_config."""
    mongo = MagicMock()
    col = MagicMock()
    col.find_one.return_value = doc
    col.update_one.return_value = MagicMock()
    mongo.db.__getitem__ = lambda self, key: col
    return mongo, col


# ---------------------------------------------------------------------------
# TestAgentesLectura
# ---------------------------------------------------------------------------


class TestAgentesLectura:
    """GET /agentes — lectura del estado."""

    def test_lista_agentes_defaults_cuando_coleccion_vacia(self):
        mongo, col = _make_mongo_mock_agentes(docs=[], pipeline_doc=None)
        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/agentes", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        body = resp.json()
        assert "agentes" in body
        assert len(body["agentes"]) == 4
        for ag in body["agentes"]:
            assert ag["estado"] == "idle"
            assert ag["ultimo_run"] is None
            assert ag["total_procesados"] == 0
            assert ag["error_msg"] is None
        assert body["pipeline_activo"] is False
        assert body["pipeline_paso_actual"] is None

    def test_lista_agentes_con_documentos_existentes(self):
        docs = [
            {"_id": "watcher", "nombre": "watcher", "estado": "error",
             "ultimo_run": "2026-04-19T10:00:00Z", "total_procesados": 5, "error_msg": "fallo"},
            {"_id": "ocr", "nombre": "ocr", "estado": "idle",
             "ultimo_run": "2026-04-19T11:00:00Z", "total_procesados": 10, "error_msg": None},
        ]
        pipeline = {"_id": "__pipeline__", "pipeline_activo": True, "pipeline_paso_actual": "ocr"}
        mongo, col = _make_mongo_mock_agentes(docs=docs, pipeline_doc=pipeline)

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/agentes", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        body = resp.json()
        agentes_map = {a["nombre"]: a for a in body["agentes"]}
        assert agentes_map["watcher"]["estado"] == "error"
        assert agentes_map["watcher"]["total_procesados"] == 5
        assert agentes_map["ocr"]["estado"] == "idle"
        assert body["pipeline_activo"] is True
        assert body["pipeline_paso_actual"] == "ocr"

    def test_sin_token_devuelve_401(self):
        with patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/agentes")
        assert resp.status_code in (401, 422)

    def test_siguiente_en_pipeline_correcto(self):
        mongo, col = _make_mongo_mock_agentes(docs=[], pipeline_doc=None)
        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/agentes", headers=_AUTH_ADMIN)

        agentes = {a["nombre"]: a for a in resp.json()["agentes"]}
        assert agentes["watcher"]["siguiente_en_pipeline"] == "ocr"
        assert agentes["ocr"]["siguiente_en_pipeline"] == "classifier"
        assert agentes["classifier"]["siguiente_en_pipeline"] == "storage"
        assert agentes["storage"]["siguiente_en_pipeline"] is None


# ---------------------------------------------------------------------------
# TestAgentesEjecutar
# ---------------------------------------------------------------------------


class TestAgentesEjecutar:
    """POST /agentes/{nombre}/ejecutar — disparo de ejecuciones."""

    def _make_col_mock(self, estado_agente=None, pipeline_doc=None):
        col = MagicMock()

        def _find_one(query, *args, **kwargs):
            _id = query.get("_id")
            if _id == "__pipeline__":
                return pipeline_doc
            if _id in ("watcher", "ocr", "classifier", "storage"):
                return estado_agente
            return None

        col.find_one.side_effect = _find_one
        col.update_one.return_value = MagicMock()
        return col

    def test_ejecutar_modo_independiente_devuelve_202(self):
        col = self._make_col_mock(estado_agente=None, pipeline_doc=None)
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.agentes._get_agente_func", return_value=MagicMock()):
                with patch("src.api.routers.auth.init_usuarios"):
                    from src.api.main import app
                    client = TestClient(app, raise_server_exceptions=True)
                    resp = client.post(
                        "/agentes/watcher/ejecutar?modo=independiente",
                        headers=_AUTH_ADMIN,
                    )

        assert resp.status_code == 202
        body = resp.json()
        assert body["agente"] == "watcher"
        assert body["modo"] == "independiente"
        assert body["siguiente_agente"] is None
        assert "id_ejecucion" in body

    def test_ejecutar_modo_pipeline_devuelve_siguiente(self):
        col = self._make_col_mock(estado_agente=None, pipeline_doc=None)
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.agentes._get_agente_func", return_value=MagicMock()):
                with patch("src.api.routers.agentes.time.sleep"):
                    with patch("src.api.routers.auth.init_usuarios"):
                        from src.api.main import app
                        client = TestClient(app, raise_server_exceptions=True)
                        resp = client.post(
                            "/agentes/ocr/ejecutar?modo=pipeline",
                            headers=_AUTH_ADMIN,
                        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["agente"] == "ocr"
        assert body["siguiente_agente"] == "classifier"

    def test_nombre_invalido_devuelve_400(self):
        mongo, col = _make_mongo_mock_agentes()
        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/agentes/inexistente/ejecutar",
                    headers=_AUTH_ADMIN,
                )
        assert resp.status_code == 400

    def test_modo_invalido_devuelve_400(self):
        mongo, col = _make_mongo_mock_agentes()
        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/agentes/watcher/ejecutar?modo=paralelo",
                    headers=_AUTH_ADMIN,
                )
        assert resp.status_code == 400

    def test_agente_running_devuelve_409(self):
        col = self._make_col_mock(
            estado_agente={"_id": "watcher", "estado": "running"},
            pipeline_doc=None,
        )
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/agentes/watcher/ejecutar",
                    headers=_AUTH_ADMIN,
                )
        assert resp.status_code == 409

    def test_pipeline_activo_devuelve_409(self):
        col = self._make_col_mock(
            estado_agente=None,
            pipeline_doc={"_id": "__pipeline__", "pipeline_activo": True, "pipeline_paso_actual": "watcher"},
        )
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/agentes/ocr/ejecutar?modo=pipeline",
                    headers=_AUTH_ADMIN,
                )
        assert resp.status_code == 409

    def test_sin_token_devuelve_401(self):
        with patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/agentes/watcher/ejecutar")
        assert resp.status_code in (401, 422)


# ---------------------------------------------------------------------------
# TestEjecutarFuncion (prueba la función _ejecutar directamente, sin HTTP)
# ---------------------------------------------------------------------------


class TestEjecutarFuncion:
    """Verifica el comportamiento de _ejecutar() en modo síncrono."""

    def _make_col(self):
        col = MagicMock()
        col.find_one.return_value = {"_id": "watcher", "total_procesados": 0}
        col.update_one.return_value = MagicMock()
        return col

    def test_modo_independiente_ejecuta_solo_el_agente(self):
        from src.api.routers.agentes import _ejecutar

        col = self._make_col()
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        mock_watcher = MagicMock()
        mock_ocr = MagicMock()

        def _fake_get_func(nombre):
            return {"watcher": mock_watcher, "ocr": mock_ocr,
                    "classifier": MagicMock(), "storage": MagicMock()}[nombre]

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.agentes._get_agente_func", side_effect=_fake_get_func):
                _ejecutar("watcher", "independiente", "abc123")

        mock_watcher.assert_called_once()
        mock_ocr.assert_not_called()

    def test_modo_pipeline_encadena_agentes_en_orden(self):
        from src.api.routers.agentes import _ejecutar

        col = self._make_col()
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        llamadas = []

        def _fake_func(nombre):
            fn = MagicMock(side_effect=lambda n=nombre: llamadas.append(n))
            return fn

        funcs = {n: _fake_func(n) for n in ["watcher", "ocr", "classifier", "storage"]}

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.agentes._get_agente_func", side_effect=lambda n: funcs[n]):
                with patch("src.api.routers.agentes.time.sleep"):
                    _ejecutar("watcher", "pipeline", "xyz")

        assert llamadas == ["watcher", "ocr", "classifier", "storage"]

    def test_pipeline_para_si_agente_falla(self):
        from src.api.routers.agentes import _ejecutar

        col = self._make_col()
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        llamadas = []

        mock_classifier = MagicMock()
        mock_storage = MagicMock()

        def _fake_get_func(nombre):
            if nombre == "watcher":
                return MagicMock(side_effect=lambda: llamadas.append("watcher"))
            if nombre == "ocr":
                def _fail():
                    llamadas.append("ocr")
                    raise RuntimeError("fallo simulado")
                return _fail
            if nombre == "classifier":
                return mock_classifier
            return mock_storage

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.agentes._get_agente_func", side_effect=_fake_get_func):
                with patch("src.api.routers.agentes.time.sleep"):
                    _ejecutar("watcher", "pipeline", "fail123")

        assert llamadas == ["watcher", "ocr"]
        mock_classifier.assert_not_called()
        mock_storage.assert_not_called()

    def test_error_se_graba_en_estado(self):
        from src.api.routers.agentes import _ejecutar

        col = self._make_col()
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        def _fake_get_func(nombre):
            return MagicMock(side_effect=RuntimeError("error test"))

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.agentes._get_agente_func", side_effect=_fake_get_func):
                _ejecutar("watcher", "independiente", "err-id")

        update_calls = col.update_one.call_args_list
        error_call = next(
            (c for c in update_calls if c.args[1].get("$set", {}).get("estado") == "error"),
            None,
        )
        assert error_call is not None
        assert "error test" in error_call.args[1]["$set"].get("error_msg", "")

    def test_pipeline_desde_ocr_omite_watcher(self):
        from src.api.routers.agentes import _ejecutar

        col = self._make_col()
        mongo = MagicMock()
        mongo.db.__getitem__ = lambda self, key: col

        llamadas = []
        mock_watcher = MagicMock()

        def _fake_get_func(nombre):
            if nombre == "watcher":
                return mock_watcher
            return MagicMock(side_effect=lambda n=nombre: llamadas.append(n))

        with patch("src.api.routers.agentes.MongoService", return_value=mongo):
            with patch("src.api.routers.agentes._get_agente_func", side_effect=_fake_get_func):
                with patch("src.api.routers.agentes.time.sleep"):
                    _ejecutar("ocr", "pipeline", "ocr-start")

        mock_watcher.assert_not_called()
        assert llamadas == ["ocr", "classifier", "storage"]


# ---------------------------------------------------------------------------
# TestConfigLlmLectura
# ---------------------------------------------------------------------------


class TestConfigLlmLectura:
    """GET /config/llm — lectura de configuración LLM."""

    def test_devuelve_defaults_cuando_no_hay_doc_en_mongo(self):
        mongo, col = _make_mongo_mock_config(doc=None)
        col.find_one.return_value = None

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/config/llm", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        body = resp.json()
        assert "provider" in body
        assert "model" in body
        assert "available_providers" in body
        assert set(body["available_providers"]) == {"openrouter", "ollama"}
        assert isinstance(body["available_models_ollama"], list)
        assert isinstance(body["available_models_openrouter"], list)

    def test_devuelve_doc_de_mongo_cuando_existe(self):
        doc = {
            "_id": "llm_config",
            "provider": "ollama",
            "model": "gemma3:12b",
            "host": "http://10.0.0.1:11434",
        }
        mongo, col = _make_mongo_mock_config(doc=doc)

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/config/llm", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        body = resp.json()
        assert body["provider"] == "ollama"
        assert body["model"] == "gemma3:12b"
        assert body["host"] == "http://10.0.0.1:11434"

    def test_sin_token_devuelve_401(self):
        with patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/config/llm")
        assert resp.status_code in (401, 422)


# ---------------------------------------------------------------------------
# TestConfigLlmEscritura
# ---------------------------------------------------------------------------


class TestConfigLlmEscritura:
    """PUT /config/llm — actualización de configuración LLM."""

    def test_put_valido_openrouter_devuelve_200(self):
        mongo, col = _make_mongo_mock_config()

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.put(
                    "/config/llm",
                    json={"provider": "openrouter", "model": "openai/gpt-4"},
                    headers=_AUTH_ADMIN,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["provider"] == "openrouter"
        assert body["model"] == "openai/gpt-4"
        assert "timestamp" in body

    def test_put_valido_ollama_con_host(self):
        mongo, col = _make_mongo_mock_config()

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.put(
                    "/config/llm",
                    json={"provider": "ollama", "model": "gemma3:12b", "host": "http://10.0.0.1:11434"},
                    headers=_AUTH_ADMIN,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["provider"] == "ollama"
        assert body["host"] == "http://10.0.0.1:11434"

    def test_put_provider_invalido_devuelve_422(self):
        mongo, col = _make_mongo_mock_config()
        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.put(
                    "/config/llm",
                    json={"provider": "chatgpt", "model": "gpt-4"},
                    headers=_AUTH_ADMIN,
                )
        assert resp.status_code == 422

    def test_put_ollama_sin_host_devuelve_400(self):
        mongo, col = _make_mongo_mock_config()
        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.put(
                    "/config/llm",
                    json={"provider": "ollama", "model": "gemma3:12b"},
                    headers=_AUTH_ADMIN,
                )
        assert resp.status_code == 400

    def test_put_persiste_en_mongo(self):
        mongo, col = _make_mongo_mock_config()

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                client.put(
                    "/config/llm",
                    json={"provider": "openrouter", "model": "openai/gpt-4"},
                    headers=_AUTH_ADMIN,
                )

        col.update_one.assert_called_once()
        call_args = col.update_one.call_args
        assert call_args.args[0] == {"_id": "llm_config"}
        assert call_args.kwargs.get("upsert") is True

    def test_sin_token_devuelve_401(self):
        with patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put("/config/llm", json={"provider": "openrouter", "model": "x"})
        assert resp.status_code in (401, 422)


# ---------------------------------------------------------------------------
# TestConfigLlmProbar
# ---------------------------------------------------------------------------


class TestConfigLlmProbar:
    """POST /config/llm/probar — test de conexión con el provider."""

    def test_probar_ollama_ok(self):
        doc = {"provider": "ollama", "model": "gemma3:12b", "host": "http://localhost:11434"}
        mongo, col = _make_mongo_mock_config(doc=doc)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"models": [{"name": "gemma3:12b"}, {"name": "mistral"}]}

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch("src.api.routers.config_llm.requests.get", return_value=mock_resp):
                with patch("src.api.routers.auth.init_usuarios"):
                    from src.api.main import app
                    client = TestClient(app, raise_server_exceptions=True)
                    resp = client.post("/config/llm/probar", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["provider"] == "ollama"
        assert "gemma3:12b" in body["modelos_disponibles"]

    def test_probar_ollama_connection_refused(self):
        import requests as req_lib

        doc = {"provider": "ollama", "model": "gemma3:12b", "host": "http://localhost:11434"}
        mongo, col = _make_mongo_mock_config(doc=doc)

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            with patch(
                "src.api.routers.config_llm.requests.get",
                side_effect=req_lib.exceptions.ConnectionError("refused"),
            ):
                with patch("src.api.routers.auth.init_usuarios"):
                    from src.api.main import app
                    client = TestClient(app, raise_server_exceptions=True)
                    resp = client.post("/config/llm/probar", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"] is not None

    def test_probar_openrouter_ok(self):
        doc = {"provider": "openrouter", "model": "openai/gpt-4", "host": None}
        mongo, col = _make_mongo_mock_config(doc=doc)

        mock_provider = MagicMock()
        mock_provider.health_check.return_value = {"status": "ok", "provider": "openrouter", "model": "openai/gpt-4"}

        with patch("src.api.routers.config_llm.MongoService", return_value=mongo):
            # OpenRouterProvider se importa localmente dentro de la función, parchar el módulo fuente
            with patch("src.services.llm.openrouter_provider.OpenRouterProvider", return_value=mock_provider):
                with patch("src.api.routers.auth.init_usuarios"):
                    from src.api.main import app
                    client = TestClient(app, raise_server_exceptions=True)
                    resp = client.post("/config/llm/probar", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["provider"] == "openrouter"

    def test_sin_token_devuelve_401(self):
        with patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/config/llm/probar")
        assert resp.status_code in (401, 422)


# ---------------------------------------------------------------------------
# TestLogs
# ---------------------------------------------------------------------------


class TestLogs:
    """GET /logs/stream y GET /logs/descargar."""

    def test_stream_devuelve_401_sin_token(self):
        with patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/logs/stream")
        assert resp.status_code in (401, 422)

    def test_stream_devuelve_200_con_token(self, tmp_path):
        """Verifica que /logs/stream devuelve 200 y Content-Type text/event-stream.

        El generador SSE es infinito; mockeamos asyncio.sleep para que lance
        una excepción después del primer keepalive, terminando el stream.
        """
        import asyncio as _asyncio

        non_existent = tmp_path / "no_existe.log"
        sleep_calls = {"count": 0}

        async def _mock_sleep(delay):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 1:
                raise RuntimeError("fin del test SSE")

        with patch("src.api.routers.logs._OPERATIONAL_LOG", non_existent):
            with patch("src.api.routers.logs.asyncio.sleep", side_effect=_mock_sleep):
                with patch("src.api.routers.auth.init_usuarios"):
                    from src.api.main import app
                    client = TestClient(app, raise_server_exceptions=False)
                    # SSE usa verify_token_sse: token como query param, no como header
                    url = f"/logs/stream?token={_TOKEN_ADMIN}"
                    with client.stream("GET", url) as resp:
                        # Headers ya comprometidos como 200 antes de que el generador falle
                        assert resp.status_code == 200
                        ct = resp.headers.get("content-type", "")
                        assert "text/event-stream" in ct

    def test_descargar_devuelve_401_sin_token(self):
        with patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/logs/descargar")
        assert resp.status_code in (401, 422)

    def test_descargar_con_archivo_existente(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        audit.write_text('{"record": {}}\n')

        with patch("src.api.routers.logs._AUDIT_LOG", audit):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/logs/descargar", headers=_AUTH_ADMIN)

        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "audit-" in cd
        assert ".jsonl" in cd

    def test_descargar_devuelve_404_si_no_existe_archivo(self, tmp_path):
        audit = tmp_path / "no_existe.jsonl"

        with patch("src.api.routers.logs._AUDIT_LOG", audit):
            with patch("src.api.routers.auth.init_usuarios"):
                from src.api.main import app
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/logs/descargar", headers=_AUTH_ADMIN)

        assert resp.status_code == 404
