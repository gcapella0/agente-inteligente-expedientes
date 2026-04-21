"""Tests para la API Fase 5 — seguridad JWT (todo mockeado)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from src.api.security import create_access_token, hash_password, verify_password

# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

_ADMIN_EMAIL = "admin@uneg.edu.ve"
_ADMIN_PASSWORD = "admin123"
_ADMIN_HASH = hash_password(_ADMIN_PASSWORD)

_USUARIO_DOC = {
    "email": _ADMIN_EMAIL,
    "password_hash": _ADMIN_HASH,
    "nombre_completo": "Administrador Sistema",
    "rol": "admin",
    "activo": True,
}

_CEDULA = "12345678"
_DOCENTE_DOC = {
    "_id": MagicMock(),
    "expediente_numero": "EXP-2026-000001",
    "docente": {
        "cedula": _CEDULA,
        "nombres": "Juan",
        "apellidos": "Pérez",
        "contacto": {},
        "direccion": {},
    },
}


def _make_mongo_mock(usuario=_USUARIO_DOC, docente=_DOCENTE_DOC):
    """Crea un MongoService mock preconfigurado."""
    mongo = MagicMock()
    usuarios_col = MagicMock()
    auditoria_col = MagicMock()

    usuarios_col.find_one.return_value = usuario
    usuarios_col.count_documents.return_value = 1
    usuarios_col.update_one.return_value = MagicMock(matched_count=1)

    mongo.db.__getitem__ = lambda self, key: {
        "usuarios": usuarios_col,
        "auditoria": auditoria_col,
    }.get(key, MagicMock())
    mongo.docentes.find_one.return_value = docente
    mongo.docentes.update_one.return_value = MagicMock(matched_count=1)

    return mongo, usuarios_col, auditoria_col


# ---------------------------------------------------------------------------
# Tests: security.py — funciones puras
# ---------------------------------------------------------------------------

class TestSecurityFunctions:
    """Tests para las funciones de security.py (sin HTTP)."""

    def test_hash_password_produce_hash_diferente_al_original(self):
        hashed = hash_password("mipassword")
        assert hashed != "mipassword"
        assert len(hashed) > 20

    def test_verify_password_correcto(self):
        hashed = hash_password("secreto123")
        assert verify_password("secreto123", hashed) is True

    def test_verify_password_incorrecto(self):
        hashed = hash_password("secreto123")
        assert verify_password("otro_password", hashed) is False

    def test_create_access_token_devuelve_string(self):
        token = create_access_token(subject="user@test.com", rol="admin")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_decodificable(self):
        from src.api.security import decode_token
        token = create_access_token(subject="user@test.com", rol="usuario")
        payload = decode_token(token)
        assert payload["sub"] == "user@test.com"
        assert payload["rol"] == "usuario"

    def test_decode_token_invalido_lanza_error(self):
        from src.api.security import decode_token
        try:
            decode_token("token.invalido.aqui")
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass

    def test_hash_sha256(self):
        from src.api.security import hash_sha256
        result = hash_sha256("texto")
        assert len(result) == 64
        assert result == hash_sha256("texto")


# ---------------------------------------------------------------------------
# Tests: /auth/login
# ---------------------------------------------------------------------------

class TestLogin:
    """Tests para POST /auth/login."""

    def test_login_exitoso(self):
        mongo_mock, usuarios_col, _ = _make_mongo_mock()
        with patch("src.api.routers.auth.MongoService", return_value=mongo_mock), \
             patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post("/auth/login", json={
                "email": _ADMIN_EMAIL,
                "password": _ADMIN_PASSWORD,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["usuario"]["email"] == _ADMIN_EMAIL
        assert data["usuario"]["rol"] == "admin"

    def test_login_email_no_existe(self):
        mongo_mock, usuarios_col, _ = _make_mongo_mock(usuario=None)
        with patch("src.api.routers.auth.MongoService", return_value=mongo_mock), \
             patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/auth/login", json={
                "email": "noexiste@uneg.edu.ve",
                "password": "cualquier",
            })
        assert resp.status_code == 401

    def test_login_password_incorrecto(self):
        mongo_mock, usuarios_col, _ = _make_mongo_mock()
        with patch("src.api.routers.auth.MongoService", return_value=mongo_mock), \
             patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/auth/login", json={
                "email": _ADMIN_EMAIL,
                "password": "password_incorrecto",
            })
        assert resp.status_code == 401

    def test_login_usuario_inactivo(self):
        usuario_inactivo = {**_USUARIO_DOC, "activo": False}
        mongo_mock, _, _ = _make_mongo_mock(usuario=usuario_inactivo)
        with patch("src.api.routers.auth.MongoService", return_value=mongo_mock), \
             patch("src.api.routers.auth.init_usuarios"):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/auth/login", json={
                "email": _ADMIN_EMAIL,
                "password": _ADMIN_PASSWORD,
            })
        assert resp.status_code == 403

    def test_login_sin_body_devuelve_422(self):
        from src.api.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/auth/login", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: endpoints protegidos requieren token
# ---------------------------------------------------------------------------

class TestEndpointsProtegidos:
    """Verifica que los endpoints de escritura requieren Authorization header."""

    def _client(self):
        from src.api.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_put_expediente_sin_token_devuelve_401_o_422(self):
        resp = self._client().put(f"/expedientes/{_CEDULA}", json={"nombres": "Ana"})
        assert resp.status_code in (401, 422)

    def test_delete_expediente_sin_token_devuelve_401_o_422(self):
        resp = self._client().delete(f"/expedientes/{_CEDULA}")
        assert resp.status_code in (401, 422)

    def test_post_documento_sin_token_devuelve_401_o_422(self):
        resp = self._client().post(f"/documentos/{_CEDULA}/agregar-documento", json={
            "tipo": "cedula_identidad",
            "nombre": "Cédula",
            "archivo_ruta": "/ruta",
            "archivo_nombre_original": "cedula.pdf",
        })
        assert resp.status_code in (401, 422)

    def test_patch_validacion_sin_token_devuelve_401_o_422(self):
        resp = self._client().patch("/documentos/507f1f77bcf86cd799439011/validacion",
                                    json={"estado": "aprobado"})
        assert resp.status_code in (401, 422)

    def test_delete_documento_sin_token_devuelve_401_o_422(self):
        resp = self._client().delete("/documentos/507f1f77bcf86cd799439011")
        assert resp.status_code in (401, 422)

    def test_auditoria_sin_token_devuelve_401_o_422(self):
        resp = self._client().get(f"/admin/auditoria/expediente/{_CEDULA}")
        assert resp.status_code in (401, 422)

    def test_token_invalido_devuelve_401(self):
        resp = self._client().put(
            f"/expedientes/{_CEDULA}",
            json={"nombres": "Ana"},
            headers={"Authorization": "Bearer token.invalido"},
        )
        assert resp.status_code == 401

    def test_token_de_usuario_no_admin_devuelve_403(self):
        token = create_access_token(subject="user@uneg.edu.ve", rol="usuario")
        mongo_mock, _, _ = _make_mongo_mock()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo_mock):
            resp = self._client().put(
                f"/expedientes/{_CEDULA}",
                json={"nombres": "Ana"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: operaciones de escritura con token admin válido
# ---------------------------------------------------------------------------

class TestEscrituraConToken:
    """Verifica que las operaciones de escritura funcionan con token admin."""

    def _admin_headers(self):
        token = create_access_token(subject=_ADMIN_EMAIL, rol="admin")
        return {"Authorization": f"Bearer {token}"}

    def test_put_expediente_con_admin_token(self):
        mongo_mock, _, _ = _make_mongo_mock()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.put(
                f"/expedientes/{_CEDULA}",
                json={"nombres": "Juan Actualizado"},
                headers=self._admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "campos_actualizados" in data

    def test_put_expediente_registra_en_auditoria(self):
        mongo_mock, _, auditoria_col = _make_mongo_mock()
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=True)
            client.put(
                f"/expedientes/{_CEDULA}",
                json={"nombres": "Juan"},
                headers=self._admin_headers(),
            )
        auditoria_col.insert_one.assert_called_once()
        evento = auditoria_col.insert_one.call_args[0][0]
        assert evento["tipo_evento"] == "expediente_actualizado"
        assert evento["usuario"] == _ADMIN_EMAIL

    def test_delete_expediente_con_admin_token(self):
        mongo_mock, _, auditoria_col = _make_mongo_mock()
        mongo_mock.documentos.delete_many.return_value = MagicMock(deleted_count=3)
        with patch("src.api.routers.expedientes_escribir.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.delete(
                f"/expedientes/{_CEDULA}",
                headers=self._admin_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["documentos_eliminados"] == 3
        auditoria_col.insert_one.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: crear usuario
# ---------------------------------------------------------------------------

class TestCrearUsuario:
    """Tests para POST /auth/crear-usuario."""

    def test_crear_usuario_sin_token_devuelve_401_o_422(self):
        from src.api.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/auth/crear-usuario", json={
            "email": "nuevo@uneg.edu.ve",
            "password": "pass123",
            "nombre_completo": "Nuevo",
        })
        assert resp.status_code in (401, 422)

    def test_crear_usuario_con_token_usuario_normal_devuelve_403(self):
        token = create_access_token(subject="user@uneg.edu.ve", rol="usuario")
        from src.api.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/auth/crear-usuario",
            json={
                "email": "nuevo@uneg.edu.ve",
                "password": "pass123",
                "nombre_completo": "Nuevo",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_crear_usuario_con_admin_token(self):
        token = create_access_token(subject=_ADMIN_EMAIL, rol="admin")
        mongo_mock, usuarios_col, _ = _make_mongo_mock()
        usuarios_col.find_one.return_value = None  # email no existe
        usuarios_col.insert_one.return_value = MagicMock(inserted_id="abc123")

        with patch("src.api.routers.auth.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post(
                "/auth/crear-usuario",
                json={
                    "email": "nuevo@uneg.edu.ve",
                    "password": "pass123",
                    "nombre_completo": "Usuario Nuevo",
                    "rol": "usuario",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 201
        assert resp.json()["email"] == "nuevo@uneg.edu.ve"

    def test_crear_usuario_email_duplicado_devuelve_400(self):
        token = create_access_token(subject=_ADMIN_EMAIL, rol="admin")
        mongo_mock, usuarios_col, _ = _make_mongo_mock()
        usuarios_col.find_one.return_value = _USUARIO_DOC  # email ya existe

        with patch("src.api.routers.auth.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/auth/crear-usuario",
                json={
                    "email": _ADMIN_EMAIL,
                    "password": "pass",
                    "nombre_completo": "Duplicado",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests: auditoría
# ---------------------------------------------------------------------------

class TestAuditoria:
    """Tests para /admin/auditoria."""

    def _admin_headers(self):
        token = create_access_token(subject=_ADMIN_EMAIL, rol="admin")
        return {"Authorization": f"Bearer {token}"}

    def test_auditoria_docente_existente(self):
        mongo_mock, _, auditoria_col = _make_mongo_mock()
        auditoria_col.find.return_value = MagicMock()
        auditoria_col.find.return_value.sort.return_value.limit.return_value = [
            {"timestamp": "2026-04-18", "tipo_evento": "expediente_actualizado",
             "usuario": _ADMIN_EMAIL, "detalles": "test", "resultado": "exitoso"}
        ]

        with patch("src.api.routers.auditoria.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(
                f"/admin/auditoria/expediente/{_CEDULA}",
                headers=self._admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["docente_cedula"] == _CEDULA
        assert "eventos" in data

    def test_auditoria_docente_inexistente_devuelve_404(self):
        mongo_mock, _, _ = _make_mongo_mock(docente=None)
        with patch("src.api.routers.auditoria.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                f"/admin/auditoria/expediente/{_CEDULA}",
                headers=self._admin_headers(),
            )
        assert resp.status_code == 404

    def test_auditoria_documento(self):
        mongo_mock, _, auditoria_col = _make_mongo_mock()
        auditoria_col.find.return_value = MagicMock()
        auditoria_col.find.return_value.sort.return_value = []

        with patch("src.api.routers.auditoria.MongoService", return_value=mongo_mock):
            from src.api.main import app
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(
                "/admin/auditoria/documento/507f1f77bcf86cd799439011",
                headers=self._admin_headers(),
            )
        assert resp.status_code == 200
        assert "eventos" in resp.json()

    def test_auditoria_con_token_usuario_normal_devuelve_403(self):
        token = create_access_token(subject="user@uneg.edu.ve", rol="usuario")
        from src.api.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            f"/admin/auditoria/expediente/{_CEDULA}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: /info y versión
# ---------------------------------------------------------------------------

class TestInfo:
    def test_version_actualizada(self):
        from src.api.main import app
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/info")
        assert resp.status_code == 200
        assert resp.json()["version"] == "2.2.0"
        assert resp.json()["autenticacion"] == "JWT Bearer"
        assert resp.json()["endpoints_totales"] == 37
