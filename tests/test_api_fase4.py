"""Tests para la API Fase 4 — escritura CRUD (todo mockeado)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bson import ObjectId
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.security import create_access_token

client = TestClient(app, raise_server_exceptions=True)

# Header de admin para endpoints protegidos
_ADMIN_HEADERS = {"Authorization": f"Bearer {create_access_token('admin@test.com', 'admin')}"}

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
        "contacto": {"email_personal": "juan@mail.com", "telefono_principal": "0424-1234567"},
        "direccion": {"direccion_completa": "Calle 1"},
    },
    "vinculacion_institucional": {"departamento": "Informática", "sede": "Caracas"},
    "completitud": {"porcentaje": 50},
    "updated_at": None,
}

_DOCUMENTO_DOC = {
    "_id": _OID2,
    "tipo": "cedula_identidad",
    "docente_cedula": _CEDULA,
    "nombre": "cedula_12345678.pdf",
    "validacion": {"estado": "pendiente"},
    "ocr": {"procesado": False},
}

_DOC_ID = str(_OID2)


# ---------------------------------------------------------------------------
# TestExpedientesEscribir — PUT y DELETE
# ---------------------------------------------------------------------------


class TestActualizarExpediente:
    def _mock_existe(self):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = dict(_DOCENTE_DOC)
        mongo.docentes.update_one.return_value = MagicMock(matched_count=1)
        return mongo

    def _mock_no_existe(self):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = None
        return mongo

    def test_actualizar_docente_no_encontrado(self):
        mongo = self._mock_no_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            r = client.put(f"/expedientes/{_CEDULA}", json={"nombres": "Nuevo"}, headers=_ADMIN_HEADERS)
        assert r.status_code == 404

    def test_actualizar_sin_datos(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            r = client.put(f"/expedientes/{_CEDULA}", json={}, headers=_ADMIN_HEADERS)
        assert r.status_code == 400

    def test_actualizar_nombres(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            r = client.put(f"/expedientes/{_CEDULA}", json={"nombres": "Carlos"}, headers=_ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["cedula"] == _CEDULA
        assert "docente.nombres" in data["campos_actualizados"]
        assert "mensaje" in data
        assert "timestamp" in data

    def test_actualizar_multiples_campos(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            r = client.put(
                f"/expedientes/{_CEDULA}",
                json={
                    "email_personal": "nuevo@mail.com",
                    "telefono_principal": "0412-9999999",
                    "departamento": "Matemáticas",
                },
                headers=_ADMIN_HEADERS,
            )
        assert r.status_code == 200
        campos = r.json()["campos_actualizados"]
        assert "docente.contacto.email_personal" in campos
        assert "docente.contacto.telefono_principal" in campos
        assert "vinculacion_institucional.departamento" in campos

    def test_actualizar_set_call_correcto(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            client.put(f"/expedientes/{_CEDULA}", json={"sede": "Maturín"}, headers=_ADMIN_HEADERS)
        # Verificar que update_one fue llamado con $set
        call_args = mongo.docentes.update_one.call_args
        assert "$set" in call_args[0][1]
        assert call_args[0][1]["$set"]["vinculacion_institucional.sede"] == "Maturín"

    def test_actualizar_incluye_updated_at(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            client.put(f"/expedientes/{_CEDULA}", json={"nombres": "Test"}, headers=_ADMIN_HEADERS)
        set_dict = mongo.docentes.update_one.call_args[0][1]["$set"]
        assert "updated_at" in set_dict


class TestEliminarExpediente:
    def _mock_existe(self, docs_count=2):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = dict(_DOCENTE_DOC)
        mongo.documentos.delete_many.return_value = MagicMock(deleted_count=docs_count)
        mongo.docentes.delete_one.return_value = MagicMock(deleted_count=1)
        return mongo

    def _mock_no_existe(self):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = None
        return mongo

    def test_eliminar_docente_no_encontrado(self):
        mongo = self._mock_no_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            r = client.delete(f"/expedientes/999999", headers=_ADMIN_HEADERS)
        assert r.status_code == 404

    def test_eliminar_exitoso(self):
        mongo = self._mock_existe(docs_count=3)
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            r = client.delete(f"/expedientes/{_CEDULA}", headers=_ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["cedula"] == _CEDULA
        assert data["documentos_eliminados"] == 3
        assert "timestamp" in data

    def test_eliminar_llama_delete_many_docs(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo):
            client.delete(f"/expedientes/{_CEDULA}", headers=_ADMIN_HEADERS)
        mongo.documentos.delete_many.assert_called_once_with({"docente_cedula": _CEDULA})
        mongo.docentes.delete_one.assert_called_once_with({"docente.cedula": _CEDULA})


# ---------------------------------------------------------------------------
# TestAgregarDocumento — POST
# ---------------------------------------------------------------------------


class TestAgregarDocumento:
    _payload = {
        "tipo": "diploma_curso",
        "nombre": "Diplomado Python",
        "archivo_ruta": "/storage/12345678/diploma.pdf",
        "archivo_nombre_original": "diploma.pdf",
        "archivo_formato": "pdf",
        "archivo_tamano_bytes": 102400,
    }

    def _mock_existe(self):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = dict(_DOCENTE_DOC)
        mongo.insert_documento.return_value = str(ObjectId())
        return mongo

    def _mock_no_existe(self):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = None
        return mongo

    def test_docente_no_encontrado(self):
        mongo = self._mock_no_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.post(f"/documentos/{_CEDULA}/agregar-documento", json=self._payload, headers=_ADMIN_HEADERS)
        assert r.status_code == 404

    def test_agregar_exitoso(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.post(f"/documentos/{_CEDULA}/agregar-documento", json=self._payload, headers=_ADMIN_HEADERS)
        assert r.status_code == 201
        data = r.json()
        assert data["docente_cedula"] == _CEDULA
        assert data["tipo"] == "diploma_curso"
        assert "documento_id" in data
        assert "timestamp" in data

    def test_agregar_llama_update_completitud(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            client.post(f"/documentos/{_CEDULA}/agregar-documento", json=self._payload, headers=_ADMIN_HEADERS)
        mongo.update_completitud.assert_called_once_with(_CEDULA)

    def test_agregar_doc_estructura_correcta(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            client.post(f"/documentos/{_CEDULA}/agregar-documento", json=self._payload, headers=_ADMIN_HEADERS)
        doc_insertado = mongo.insert_documento.call_args[0][0]
        assert doc_insertado["validacion"]["estado"] == "pendiente"
        assert doc_insertado["ocr"]["procesado"] is False
        assert doc_insertado["metadata"]["metodo_carga"] == "carga_manual"
        assert doc_insertado["docente_cedula"] == _CEDULA

    def test_campos_requeridos_faltantes(self):
        with patch("src.api.routers.documentos_escribir.MongoService"):
            r = client.post(f"/documentos/{_CEDULA}/agregar-documento", json={"tipo": "diploma_curso"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# TestActualizarValidacion — PATCH
# ---------------------------------------------------------------------------


class TestActualizarValidacion:
    def _mock_existe(self):
        mongo = MagicMock()
        mongo.documentos.find_one.return_value = dict(_DOCUMENTO_DOC)
        mongo.documentos.update_one.return_value = MagicMock(matched_count=1)
        return mongo

    def _mock_no_existe(self):
        mongo = MagicMock()
        mongo.documentos.find_one.return_value = None
        return mongo

    def test_id_invalido(self):
        with patch("src.api.routers.documentos_escribir.MongoService"):
            r = client.patch("/documentos/no-es-objectid/validacion", json={"estado": "aprobado"})
        assert r.status_code == 422

    def test_estado_invalido(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.patch(f"/documentos/{_DOC_ID}/validacion", json={"estado": "inventado"})
        assert r.status_code == 422

    def test_documento_no_encontrado(self):
        mongo = self._mock_no_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.patch(f"/documentos/{_DOC_ID}/validacion", json={"estado": "aprobado"}, headers=_ADMIN_HEADERS)
        assert r.status_code == 404

    def test_actualizar_estado_aprobado(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.patch(f"/documentos/{_DOC_ID}/validacion", json={"estado": "aprobado"}, headers=_ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["estado"] == "aprobado"
        assert data["documento_id"] == _DOC_ID

    def test_actualizar_con_observaciones(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.patch(
                f"/documentos/{_DOC_ID}/validacion",
                json={"estado": "rechazado", "observaciones": "Ilegible"},
                headers=_ADMIN_HEADERS,
            )
        assert r.status_code == 200
        set_dict = mongo.documentos.update_one.call_args[0][1]["$set"]
        assert set_dict["validacion.observaciones"] == "Ilegible"

    def test_todos_los_estados_validos(self):
        for estado in ("pendiente", "aprobado", "rechazado", "requiere_revision"):
            mongo = self._mock_existe()
            with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
                r = client.patch(f"/documentos/{_DOC_ID}/validacion", json={"estado": estado}, headers=_ADMIN_HEADERS)
            assert r.status_code == 200, f"Estado {estado!r} debería ser válido"

    def test_actualizar_llama_update_completitud(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            client.patch(f"/documentos/{_DOC_ID}/validacion", json={"estado": "aprobado"}, headers=_ADMIN_HEADERS)
        mongo.update_completitud.assert_called_once_with(_CEDULA)


# ---------------------------------------------------------------------------
# TestEliminarDocumento — DELETE
# ---------------------------------------------------------------------------


class TestEliminarDocumento:
    def _mock_existe(self):
        mongo = MagicMock()
        mongo.documentos.find_one.return_value = dict(_DOCUMENTO_DOC)
        mongo.documentos.delete_one.return_value = MagicMock(deleted_count=1)
        return mongo

    def _mock_no_existe(self):
        mongo = MagicMock()
        mongo.documentos.find_one.return_value = None
        return mongo

    def test_id_invalido(self):
        with patch("src.api.routers.documentos_escribir.MongoService"):
            r = client.delete("/documentos/no-es-objectid")
        assert r.status_code == 422

    def test_documento_no_encontrado(self):
        mongo = self._mock_no_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.delete(f"/documentos/{_DOC_ID}", headers=_ADMIN_HEADERS)
        assert r.status_code == 404

    def test_eliminar_exitoso(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            r = client.delete(f"/documentos/{_DOC_ID}", headers=_ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["documento_id"] == _DOC_ID
        assert data["docente_cedula"] == _CEDULA
        assert data["tipo"] == "cedula_identidad"

    def test_eliminar_llama_update_completitud(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            client.delete(f"/documentos/{_DOC_ID}", headers=_ADMIN_HEADERS)
        mongo.update_completitud.assert_called_once_with(_CEDULA)

    def test_eliminar_llama_delete_one(self):
        mongo = self._mock_existe()
        with patch("src.api.routers.documentos_escribir.MongoService", return_value=mongo):
            client.delete(f"/documentos/{_DOC_ID}", headers=_ADMIN_HEADERS)
        mongo.documentos.delete_one.assert_called_once_with({"_id": _OID2})
