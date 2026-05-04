"""Tests para los endpoints CRUD /usuarios (todo mockeado)."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bson import ObjectId
from fastapi.testclient import TestClient

from src.api.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = create_access_token(subject="admin@uneg.edu.ve", rol="admin")
_USER_TOKEN = create_access_token(subject="docente@uneg.edu.ve", rol="docente")

_USER_ID = str(ObjectId())
_USER_DOC = {
    "_id": ObjectId(_USER_ID),
    "email": "docente@uneg.edu.ve",
    "rol": "docente",
    "activo": True,
    "creado_en": None,
}

_HEADERS_ADMIN = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}
_HEADERS_USER = {"Authorization": f"Bearer {_USER_TOKEN}"}


def _make_usuarios_col(find_one_result=None, find_result=None, inserted_id=None):
    col = MagicMock()
    col.find_one.return_value = find_one_result
    col.find.return_value = find_result or []
    col.insert_one.return_value = MagicMock(inserted_id=ObjectId(inserted_id or _USER_ID))
    col.update_one.return_value = MagicMock(matched_count=1)
    col.delete_one.return_value = MagicMock(deleted_count=1)
    col.count_documents.return_value = 1
    return col


@contextmanager
def _client(usuarios_col):
    """Context manager que mantiene los patches activos durante las requests."""
    mongo = MagicMock()
    mongo.db.__getitem__ = lambda self, key: usuarios_col if key == "usuarios" else MagicMock()

    with patch("src.api.routers.usuarios.MongoService", return_value=mongo), \
         patch("src.api.routers.auth.init_usuarios"):
        from src.api.main import app
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /usuarios
# ---------------------------------------------------------------------------

class TestGetUsuarios:
    def test_sin_jwt_retorna_422(self):
        # FastAPI retorna 422 cuando falta un header requerido
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.get("/usuarios/")
        assert resp.status_code == 422

    def test_jwt_no_admin_retorna_403(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.get("/usuarios/", headers=_HEADERS_USER)
        assert resp.status_code == 403

    def test_admin_retorna_lista(self):
        col = _make_usuarios_col(find_result=[{**_USER_DOC}])
        with _client(col) as client:
            resp = client.get("/usuarios/", headers=_HEADERS_ADMIN)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["email"] == "docente@uneg.edu.ve"

    def test_lista_vacia(self):
        col = _make_usuarios_col(find_result=[])
        with _client(col) as client:
            resp = client.get("/usuarios/", headers=_HEADERS_ADMIN)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_password_no_en_respuesta(self):
        doc = {**_USER_DOC, "password_hash": hash_password("secreto")}
        col = _make_usuarios_col(find_result=[doc])
        with _client(col) as client:
            resp = client.get("/usuarios/", headers=_HEADERS_ADMIN)
        assert resp.status_code == 200
        for u in resp.json():
            assert "password" not in u
            assert "password_hash" not in u


# ---------------------------------------------------------------------------
# POST /usuarios/crear
# ---------------------------------------------------------------------------

class TestCrearUsuario:
    def test_sin_jwt_retorna_422(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.post("/usuarios/crear",
                               json={"email": "x@y.com", "password": "123456", "rol": "docente"})
        assert resp.status_code == 422

    def test_jwt_no_admin_retorna_403(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.post("/usuarios/crear",
                               json={"email": "x@y.com", "password": "123456", "rol": "docente"},
                               headers=_HEADERS_USER)
        assert resp.status_code == 403

    def test_crear_usuario_exitoso(self):
        col = _make_usuarios_col(find_one_result=None)
        with _client(col) as client:
            resp = client.post("/usuarios/crear",
                               json={"email": "nuevo@uneg.edu.ve", "password": "secreta", "rol": "docente"},
                               headers=_HEADERS_ADMIN)
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "nuevo@uneg.edu.ve"
        assert data["rol"] == "docente"
        assert "id" in data
        assert "password" not in data
        assert "password_hash" not in data

    def test_email_invalido_retorna_400(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.post("/usuarios/crear",
                               json={"email": "sinArroba", "password": "123456", "rol": "docente"},
                               headers=_HEADERS_ADMIN)
        assert resp.status_code == 400

    def test_password_corta_retorna_400(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.post("/usuarios/crear",
                               json={"email": "x@y.com", "password": "123", "rol": "docente"},
                               headers=_HEADERS_ADMIN)
        assert resp.status_code == 400

    def test_rol_invalido_retorna_400(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.post("/usuarios/crear",
                               json={"email": "x@y.com", "password": "123456", "rol": "superusuario"},
                               headers=_HEADERS_ADMIN)
        assert resp.status_code == 400

    def test_email_duplicado_retorna_400(self):
        col = _make_usuarios_col(find_one_result=_USER_DOC)
        with _client(col) as client:
            resp = client.post("/usuarios/crear",
                               json={"email": "docente@uneg.edu.ve", "password": "123456", "rol": "docente"},
                               headers=_HEADERS_ADMIN)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PUT /usuarios/{id}/rol
# ---------------------------------------------------------------------------

class TestActualizarRol:
    def test_sin_jwt_retorna_422(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.put(f"/usuarios/{_USER_ID}/rol", json={"rol": "admin"})
        assert resp.status_code == 422

    def test_jwt_no_admin_retorna_403(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.put(f"/usuarios/{_USER_ID}/rol", json={"rol": "admin"}, headers=_HEADERS_USER)
        assert resp.status_code == 403

    def test_actualizar_rol_exitoso(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.put(f"/usuarios/{_USER_ID}/rol", json={"rol": "admin"}, headers=_HEADERS_ADMIN)
        assert resp.status_code == 200
        assert resp.json()["message"] == "Rol actualizado"

    def test_rol_invalido_retorna_400(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.put(f"/usuarios/{_USER_ID}/rol", json={"rol": "superusuario"}, headers=_HEADERS_ADMIN)
        assert resp.status_code == 400

    def test_id_invalido_retorna_400(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.put("/usuarios/id-invalido/rol", json={"rol": "admin"}, headers=_HEADERS_ADMIN)
        assert resp.status_code == 400

    def test_usuario_no_encontrado_retorna_404(self):
        col = _make_usuarios_col()
        col.update_one.return_value = MagicMock(matched_count=0)
        with _client(col) as client:
            resp = client.put(f"/usuarios/{_USER_ID}/rol", json={"rol": "viewer"}, headers=_HEADERS_ADMIN)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /usuarios/{id}
# ---------------------------------------------------------------------------

class TestEliminarUsuario:
    def test_sin_jwt_retorna_422(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.delete(f"/usuarios/{_USER_ID}")
        assert resp.status_code == 422

    def test_jwt_no_admin_retorna_403(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.delete(f"/usuarios/{_USER_ID}", headers=_HEADERS_USER)
        assert resp.status_code == 403

    def test_eliminar_usuario_exitoso(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.delete(f"/usuarios/{_USER_ID}", headers=_HEADERS_ADMIN)
        assert resp.status_code == 200
        assert resp.json()["message"] == "Usuario eliminado"

    def test_id_invalido_retorna_400(self):
        col = _make_usuarios_col()
        with _client(col) as client:
            resp = client.delete("/usuarios/id-invalido", headers=_HEADERS_ADMIN)
        assert resp.status_code == 400

    def test_usuario_no_encontrado_retorna_404(self):
        col = _make_usuarios_col()
        col.delete_one.return_value = MagicMock(deleted_count=0)
        with _client(col) as client:
            resp = client.delete(f"/usuarios/{_USER_ID}", headers=_HEADERS_ADMIN)
        assert resp.status_code == 404
