"""Tests para FileService, MongoService y StorageAgent."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.file_service import FileService
from src.services.mongo_service import MongoService
from src.agents.storage_agent import StorageAgent


# ---------------------------------------------------------------------------
# Constantes de prueba
# ---------------------------------------------------------------------------

CLASSIFIED_RESULT_VALIDO = {
    "archivo_path": Path("/tmp/test/titulo.pdf"),
    "archivo_nombre": "titulo.pdf",
    "carpeta_origen": "Maria_Elena_Garcia",
    "formato": "pdf",
    "tamano_bytes": 2048,
    "hash_sha256": "abc123deadbeef",
    "ocr_resultado": {
        "texto_completo": "República Bolivariana de Venezuela...",
        "json_export": {},
        "json_ligero": {"pages": []},
        "confianza_promedio": 0.95,
        "paginas": 1,
        "idioma_detectado": "es",
        "palabras_detectadas": 80,
    },
    "clasificacion": {
        "valido": True,
        "tipo": "titulo_universitario",
        "razon_rechazo": None,
        "campos_extraidos": {
            "nombre_titular": "María Elena García",
            "cedula_titular": "V-12345678",
            "institucion_emisora": "UNEG",
            "titulo_otorgado": "Licenciada en Educación",
            "fecha_emision": "20150715",
        },
        "confianza_clasificacion": 0.92,
        "modelo_llm": "openrouter/hunter-alpha",
        "tokens_usados": 150,
    },
}

CLASSIFIED_RESULT_NO_VALIDO = {
    **CLASSIFIED_RESULT_VALIDO,
    "clasificacion": {
        "valido": False,
        "tipo": "no_valido",
        "razon_rechazo": "No es un documento académico",
        "campos_extraidos": {},
        "confianza_clasificacion": 0.88,
        "modelo_llm": "openrouter/hunter-alpha",
        "tokens_usados": 80,
    },
}

CLASSIFIED_RESULT_SIN_CEDULA = {
    **CLASSIFIED_RESULT_VALIDO,
    "clasificacion": {
        **CLASSIFIED_RESULT_VALIDO["clasificacion"],
        "campos_extraidos": {"nombre_titular": "Juan Pérez"},
    },
}

CLASSIFIED_RESULT_RIF = {
    **CLASSIFIED_RESULT_VALIDO,
    "archivo_nombre": "rif.pdf",
    "clasificacion": {
        **CLASSIFIED_RESULT_VALIDO["clasificacion"],
        "tipo": "rif",
        "campos_extraidos": {
            "nombre_titular": "Juan Pérez",
            "numero_rif": "V-198007201",  # cédula=19800720, verificador=1
        },
    },
}

CLASSIFIED_RESULT_CURRICULO_VITAE = {
    **CLASSIFIED_RESULT_VALIDO,
    "archivo_nombre": "cv.pdf",
    "clasificacion": {
        **CLASSIFIED_RESULT_VALIDO["clasificacion"],
        "tipo": "curriculo_vitae",
        "campos_extraidos": {
            "nombre_titular": "María Elena García",
            "cedula_titular": "V-12345678",
            "correo_electronico": "mgarcia@uneg.edu.ve",
            "telefono": "0424-1234567",
            "titulo_academico": "Magíster en Educación",
            "institucion_emisora": "Universidad Central de Venezuela",
        },
    },
}

# Docente devuelto por MongoDB (simula find_one)
MONGO_DOCENTE = {
    "_id": "507f1f77bcf86cd799439011",
    "expediente_numero": "EXP-2026-000001",
    "docente": {"cedula": "12345678", "nombres": "María Elena", "apellidos": "García"},
}

MONGO_DOCUMENTO = {
    "_id": "507f1f77bcf86cd799439022",
    "tipo": "titulo_universitario",
    "archivo": {"hash_sha256": "abc123deadbeef"},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_mongo_service():
    """Retorna un MongoService con las colecciones mockeadas."""

    def factory(
        docente_exists: bool = False,
        documento_hash_exists: bool = False,
        should_fail: bool = False,
        insert_id: str = "507f1f77bcf86cd799439011",
    ) -> MongoService:
        with patch.object(MongoService, "__init__", lambda self: None):
            service = MongoService()
            service.docentes = MagicMock()
            service.documentos = MagicMock()

        if should_fail:
            from pymongo.errors import PyMongoError
            error = PyMongoError("Error simulado de MongoDB")
            service.docentes.find_one.side_effect = error
            service.documentos.find_one.side_effect = error
            service.docentes.insert_one.side_effect = error
            service.documentos.insert_one.side_effect = error
        else:
            # find_docente_by_cedula
            service.docentes.find_one.return_value = MONGO_DOCENTE if docente_exists else None
            # find_documento_by_hash
            service.documentos.find_one.return_value = MONGO_DOCUMENTO if documento_hash_exists else None

            # insert returns
            insert_result = MagicMock()
            insert_result.inserted_id = insert_id
            service.docentes.insert_one.return_value = insert_result
            service.documentos.insert_one.return_value = insert_result

            # find para update_completitud
            service.documentos.find.return_value = [{"_id": "id001", "tipo": "titulo_universitario"}]
            # update_one
            service.docentes.update_one.return_value = MagicMock()
            service.documentos.update_one.return_value = MagicMock()
            # count_documents para generate_expediente_numero
            service.docentes.count_documents.return_value = 0

        return service

    return factory


@pytest.fixture
def fake_file_service(tmp_path):
    """Retorna un FileService con move_to_storage configurable."""

    def factory(move_should_fail: bool = False) -> FileService:
        service = FileService()
        if move_should_fail:
            # Reemplaza el método estático en la instancia con lambda que falla
            service.__class__.move_to_storage = staticmethod(
                lambda *a, **kw: (_ for _ in ()).throw(OSError("Error de I/O simulado"))
            )
        else:
            destino = tmp_path / "storage" / "12345678" / "titulo_universitario_20150715.pdf"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.touch()
            service.__class__.move_to_storage = staticmethod(lambda *a, **kw: destino)
        return service

    return factory


@pytest.fixture
def fake_storage(fake_mongo_service, fake_file_service):
    """Retorna un StorageAgent con dependencias mockeadas."""

    def factory(
        docente_exists: bool = False,
        documento_hash_exists: bool = False,
        mongo_should_fail: bool = False,
        move_should_fail: bool = False,
    ) -> StorageAgent:
        mongo = fake_mongo_service(
            docente_exists=docente_exists,
            documento_hash_exists=documento_hash_exists,
            should_fail=mongo_should_fail,
        )
        files = fake_file_service(move_should_fail=move_should_fail)
        # Parchamos los métodos de la instancia para evitar efectos secundarios
        # en el método directo (find_docente_by_cedula, etc.)
        agent = StorageAgent(mongo, files)
        return agent

    return factory


# ---------------------------------------------------------------------------
# Tests: FileService
# ---------------------------------------------------------------------------

class TestFileServiceComputeHash:
    def test_hash_correcto(self, tmp_path):
        archivo = tmp_path / "test.pdf"
        archivo.write_bytes(b"contenido de prueba")
        hash_result = FileService.compute_hash(archivo)
        import hashlib
        esperado = hashlib.sha256(b"contenido de prueba").hexdigest()
        assert hash_result == esperado

    def test_hash_archivo_inexistente_lanza_error(self, tmp_path):
        with pytest.raises(OSError):
            FileService.compute_hash(tmp_path / "no_existe.pdf")

    def test_hash_archivo_grande_en_chunks(self, tmp_path):
        """Verifica que archivos > 8192 bytes se procesen correctamente."""
        archivo = tmp_path / "grande.bin"
        contenido = b"x" * 100_000
        archivo.write_bytes(contenido)
        import hashlib
        esperado = hashlib.sha256(contenido).hexdigest()
        assert FileService.compute_hash(archivo) == esperado


class TestFileServiceMoveToStorage:
    def test_mueve_archivo_exitosamente(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.services.file_service.config.STORAGE_DIR", tmp_path / "storage")
        origen = tmp_path / "titulo.pdf"
        origen.write_bytes(b"datos pdf")

        destino = FileService.move_to_storage(origen, "12345678", "titulo_universitario", "20150715")

        assert destino.exists()
        assert destino.name == "titulo_universitario_20150715.pdf"
        assert not origen.exists()

    def test_crea_directorio_de_cedula(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.services.file_service.config.STORAGE_DIR", tmp_path / "storage")
        origen = tmp_path / "doc.pdf"
        origen.write_bytes(b"x")

        destino = FileService.move_to_storage(origen, "99999999", "cedula_identidad", "20200101")

        assert (tmp_path / "storage" / "99999999").is_dir()

    def test_nombre_sin_fecha_usa_fecha_actual(self, tmp_path, monkeypatch):
        from datetime import datetime
        monkeypatch.setattr("src.services.file_service.config.STORAGE_DIR", tmp_path / "storage")
        fecha_mock = datetime(2026, 3, 25)
        monkeypatch.setattr(
            "src.services.file_service.datetime",
            type("dt", (), {"now": staticmethod(lambda: fecha_mock)})(),
        )
        origen = tmp_path / "rif.pdf"
        origen.write_bytes(b"rif")

        destino = FileService.move_to_storage(origen, "11111111", "rif", None)

        assert "20260325" in destino.name

    def test_colision_agrega_sufijo(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.services.file_service.config.STORAGE_DIR", tmp_path / "storage")
        storage_dir = tmp_path / "storage" / "12345678"
        storage_dir.mkdir(parents=True)
        # Crear archivo con el nombre esperado para forzar colisión
        (storage_dir / "cedula_identidad_20200101.pdf").write_bytes(b"existente")

        origen = tmp_path / "cedula.pdf"
        origen.write_bytes(b"nuevo")

        destino = FileService.move_to_storage(origen, "12345678", "cedula_identidad", "20200101")

        assert destino.name == "cedula_identidad_20200101_1.pdf"

    def test_colision_multiple_sufijos(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.services.file_service.config.STORAGE_DIR", tmp_path / "storage")
        storage_dir = tmp_path / "storage" / "12345678"
        storage_dir.mkdir(parents=True)
        (storage_dir / "cedula_identidad_20200101.pdf").write_bytes(b"1")
        (storage_dir / "cedula_identidad_20200101_1.pdf").write_bytes(b"2")

        origen = tmp_path / "cedula.pdf"
        origen.write_bytes(b"3")

        destino = FileService.move_to_storage(origen, "12345678", "cedula_identidad", "20200101")

        assert destino.name == "cedula_identidad_20200101_2.pdf"

    def test_extension_preservada(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.services.file_service.config.STORAGE_DIR", tmp_path / "storage")
        origen = tmp_path / "imagen.jpg"
        origen.write_bytes(b"img")

        destino = FileService.move_to_storage(origen, "55555555", "cedula_identidad", "20210101")

        assert destino.suffix == ".jpg"


class TestFileServiceCleanup:
    def test_elimina_archivos_del_directorio(self, tmp_path):
        d = tmp_path / "docente_a"
        d.mkdir()
        (d / "file1.pdf").write_bytes(b"a")
        (d / "file2.pdf").write_bytes(b"b")

        count = FileService.cleanup_input_directory(d)

        assert count == 2
        assert not (d / "file1.pdf").exists()

    def test_elimina_directorio_si_queda_vacio(self, tmp_path):
        d = tmp_path / "docente_b"
        d.mkdir()
        (d / "doc.pdf").write_bytes(b"x")

        FileService.cleanup_input_directory(d)

        assert not d.exists()

    def test_no_elimina_directorio_con_archivos_restantes(self, tmp_path):
        """Si quedan subdirectorios, el directorio no se elimina."""
        d = tmp_path / "docente_c"
        d.mkdir()
        subdir = d / "sub"
        subdir.mkdir()
        (d / "doc.pdf").write_bytes(b"x")

        FileService.cleanup_input_directory(d)

        assert d.exists()  # No eliminado por el subdirectorio

    def test_directorio_inexistente_retorna_cero(self, tmp_path):
        count = FileService.cleanup_input_directory(tmp_path / "no_existe")
        assert count == 0

    def test_directorio_vacio_retorna_cero(self, tmp_path):
        d = tmp_path / "vacio"
        d.mkdir()
        count = FileService.cleanup_input_directory(d)
        assert count == 0


# ---------------------------------------------------------------------------
# Tests: MongoService
# ---------------------------------------------------------------------------

class TestMongoServiceInit:
    def test_inicializacion_crea_colecciones(self, monkeypatch):
        mock_client = MagicMock()
        monkeypatch.setattr("src.services.mongo_service.MongoClient", lambda uri: mock_client)
        with patch.object(MongoService, "setup_indexes", lambda self: None):
            service = MongoService()
        assert hasattr(service, "docentes")
        assert hasattr(service, "documentos")

    def test_setup_indexes_no_crashea_con_error(self, monkeypatch):
        from pymongo.errors import PyMongoError
        mock_client = MagicMock()
        mock_client.__getitem__.return_value.__getitem__.return_value.create_index.side_effect = PyMongoError("fallo")
        monkeypatch.setattr("src.services.mongo_service.MongoClient", lambda uri: mock_client)
        # No debe lanzar excepción
        MongoService()


class TestMongoServiceFindDocente:
    def test_find_docente_existente(self, fake_mongo_service):
        service = fake_mongo_service(docente_exists=True)
        resultado = service.find_docente_by_cedula("12345678")
        assert resultado is not None
        assert resultado["docente"]["cedula"] == "12345678"

    def test_find_docente_inexistente_retorna_none(self, fake_mongo_service):
        service = fake_mongo_service(docente_exists=False)
        # Mockeamos find_one directamente para que retorne None según el campo
        service.docentes.find_one.return_value = None
        resultado = service.find_docente_by_cedula("99999999")
        assert resultado is None

    def test_find_docente_error_mongo_lanza_excepcion(self, fake_mongo_service):
        from pymongo.errors import PyMongoError
        service = fake_mongo_service()
        service.docentes.find_one.side_effect = PyMongoError("timeout")
        with pytest.raises(PyMongoError):
            service.find_docente_by_cedula("12345678")


class TestMongoServiceFindDocumento:
    def test_find_documento_por_hash_existente(self, fake_mongo_service):
        service = fake_mongo_service(documento_hash_exists=True)
        resultado = service.find_documento_by_hash("abc123deadbeef")
        assert resultado is not None

    def test_find_documento_por_hash_inexistente(self, fake_mongo_service):
        service = fake_mongo_service(documento_hash_exists=False)
        service.documentos.find_one.return_value = None
        resultado = service.find_documento_by_hash("nohash")
        assert resultado is None


class TestMongoServiceInsert:
    def test_insert_docente_retorna_id_string(self, fake_mongo_service):
        service = fake_mongo_service(insert_id="507f1f77bcf86cd799439099")
        datos = {
            "expediente_numero": None,
            "status": "incompleto",
            "docente": {"cedula": "11111111", "nombres": "Juan", "apellidos": "Pérez"},
            "formacion_academica": [],
            "vinculacion_institucional": {},
            "completitud": {"porcentaje": 0, "documentos_requeridos": [], "documentos_faltantes": []},
            "created_at": __import__("datetime").datetime.now(),
            "updated_at": __import__("datetime").datetime.now(),
        }
        resultado = service.insert_docente(datos)
        assert isinstance(resultado, str)
        assert resultado == "507f1f77bcf86cd799439099"

    def test_insert_docente_datos_invalidos_lanza_error(self, fake_mongo_service):
        service = fake_mongo_service()
        with pytest.raises(Exception):
            service.insert_docente({"cedula": "sin_modelo"})

    def test_insert_documento_retorna_id_string(self, fake_mongo_service):
        from datetime import datetime
        service = fake_mongo_service(insert_id="507f1f77bcf86cd799439088")
        datos = {
            "docente_id": "507f1f77bcf86cd799439011",
            "docente_cedula": "12345678",
            "tipo": "titulo_universitario",
            "nombre": "titulo.pdf",
            "archivo": {
                "ruta": "/tmp/titulo.pdf",
                "nombre_original": "titulo.pdf",
                "formato": "pdf",
            },
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        resultado = service.insert_documento(datos)
        assert isinstance(resultado, str)
        assert resultado == "507f1f77bcf86cd799439088"

    def test_insert_documento_datos_invalidos_lanza_error(self, fake_mongo_service):
        service = fake_mongo_service()
        with pytest.raises(Exception):
            service.insert_documento({"tipo": "cedula_identidad"})

    def test_insert_mongo_error_lanza_excepcion(self, fake_mongo_service):
        from pymongo.errors import PyMongoError
        from datetime import datetime
        service = fake_mongo_service()
        service.docentes.insert_one.side_effect = PyMongoError("dup key")
        datos = {
            "expediente_numero": None,
            "status": "incompleto",
            "docente": {"cedula": "22222222", "nombres": "Ana", "apellidos": "López"},
            "formacion_academica": [],
            "vinculacion_institucional": {},
            "completitud": {"porcentaje": 0, "documentos_requeridos": [], "documentos_faltantes": []},
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        with pytest.raises(PyMongoError):
            service.insert_docente(datos)


class TestMongoServiceCompletitud:
    def test_update_completitud_calcula_porcentaje(self, fake_mongo_service):
        service = fake_mongo_service()
        service.documentos.find.return_value = [
            {"_id": "id1", "tipo": "titulo_universitario"},
            {"_id": "id2", "tipo": "cedula_identidad"},
        ]
        service.update_completitud("12345678")
        service.docentes.update_one.assert_called_once()
        call_args = service.docentes.update_one.call_args
        set_data = call_args[0][1]["$set"]
        # 2 de 10 = 20%
        assert set_data["completitud.porcentaje"] == 20
        assert set_data["completitud.documentos_ids"] == ["id1", "id2"]

    def test_update_completitud_todos_presentes(self, fake_mongo_service):
        service = fake_mongo_service()
        tipos = [
            "cedula_identidad", "partida_nacimiento", "rif", "titulo_bachiller",
            "certificado_notas_bachillerato", "titulo_universitario",
            "certificado_notas_pregrado", "fondo_negro_titulo", "acta_grado",
            "resolucion_nombramiento",
        ]
        service.documentos.find.return_value = [
            {"_id": f"id{i}", "tipo": t} for i, t in enumerate(tipos)
        ]
        service.update_completitud("12345678")
        set_data = service.docentes.update_one.call_args[0][1]["$set"]
        assert set_data["completitud.porcentaje"] == 100
        assert set_data["completitud.documentos_faltantes"] == []
        assert len(set_data["completitud.documentos_ids"]) == 10

    def test_update_completitud_ninguno_presente(self, fake_mongo_service):
        service = fake_mongo_service()
        service.documentos.find.return_value = []
        service.update_completitud("12345678")
        set_data = service.docentes.update_one.call_args[0][1]["$set"]
        assert set_data["completitud.porcentaje"] == 0
        assert len(set_data["completitud.documentos_faltantes"]) == 10
        assert set_data["completitud.documentos_ids"] == []


class TestMongoServiceExpedienteNumero:
    def test_formato_correcto(self, fake_mongo_service):
        service = fake_mongo_service()
        service.docentes.count_documents.return_value = 0
        numero = service.generate_expediente_numero()
        import re
        assert re.match(r"EXP-\d{4}-\d{6}", numero)

    def test_secuencia_incrementa(self, fake_mongo_service):
        service = fake_mongo_service()
        service.docentes.count_documents.return_value = 5
        numero = service.generate_expediente_numero()
        year = __import__("datetime").datetime.now().year
        assert numero == f"EXP-{year}-000006"


# ---------------------------------------------------------------------------
# Tests: StorageAgent.process
# ---------------------------------------------------------------------------

class TestStorageAgentProcess:
    def test_proceso_exitoso_completo(self, fake_storage, monkeypatch):
        agent = fake_storage()
        # Parchamos directamente los métodos de mongo_service de la instancia
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        agent.mongo_service.insert_docente = MagicMock(return_value="did001")
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()

        resultado = agent.process(CLASSIFIED_RESULT_VALIDO)

        assert resultado["exito"] is True
        assert resultado["accion"] == "insert"
        assert resultado["docente_id"] == "did001"
        assert resultado["documento_id"] == "doc001"

    def test_documento_no_valido_retorna_skip(self, fake_storage):
        agent = fake_storage()
        resultado = agent.process(CLASSIFIED_RESULT_NO_VALIDO)
        assert resultado["exito"] is False
        assert resultado["accion"] == "skip"

    def test_sin_cedula_sin_carpeta_retorna_error(self, fake_storage):
        result_sin_todo = {
            **CLASSIFIED_RESULT_SIN_CEDULA,
            "carpeta_origen": "",
        }
        agent = fake_storage()
        agent.mongo_service.docentes = MagicMock()
        agent.mongo_service.docentes.find.return_value = []
        resultado = agent.process(result_sin_todo)
        assert resultado["exito"] is False
        assert resultado["accion"] == "error"

    def test_sin_cedula_fallback_carpeta_vincula_docente_existente(self, fake_storage):
        result_extranjero = {
            **CLASSIFIED_RESULT_SIN_CEDULA,
            "carpeta_origen": "Genghis_Capella",
        }
        agent = fake_storage()
        agent.mongo_service.docentes = MagicMock()
        agent.mongo_service.docentes.find.return_value = [
            {"docente": {"cedula": "19800720"}}
        ]
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=MONGO_DOCENTE)
        resultado = agent.process(result_extranjero)
        assert resultado["exito"] is True
        agent.mongo_service.find_docente_by_cedula.assert_called_once_with("19800720")

    def test_sin_cedula_fallback_carpeta_ambigua_usa_provisional(self, fake_storage):
        result_extranjero = {
            **CLASSIFIED_RESULT_SIN_CEDULA,
            "carpeta_origen": "Juan_Perez",
        }
        agent = fake_storage()
        agent.mongo_service.docentes = MagicMock()
        agent.mongo_service.docentes.find.return_value = [
            {"docente": {"cedula": "11111111"}},
            {"docente": {"cedula": "22222222"}},
        ]
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        agent.mongo_service.insert_docente = MagicMock(return_value="nuevo_id")
        resultado = agent.process(result_extranjero)
        assert resultado["exito"] is True
        agent.mongo_service.find_docente_by_cedula.assert_called_once_with("Juan_Perez")

    def test_sin_cedula_crea_docente_provisional_con_carpeta(self, fake_storage):
        result_extranjero = {
            **CLASSIFIED_RESULT_SIN_CEDULA,
            "carpeta_origen": "Genghis_Capella",
        }
        agent = fake_storage()
        agent.mongo_service.docentes = MagicMock()
        agent.mongo_service.docentes.find.return_value = []  # Sin match en búsqueda por nombre
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        agent.mongo_service.insert_docente = MagicMock(return_value="nuevo_id")
        resultado = agent.process(result_extranjero)
        assert resultado["exito"] is True
        agent.mongo_service.find_docente_by_cedula.assert_called_once_with("Genghis_Capella")

    def test_provisional_vinculado_a_cedula_real(self, fake_storage):
        """Docente provisional creado por carpeta se fusiona al recibir cédula real."""
        result_rif_con_carpeta = {
            **CLASSIFIED_RESULT_RIF,
            "carpeta_origen": "Genghis_Capella",
        }
        provisional_doc = {
            "_id": "prov_id_001",
            "docente": {"cedula": "Genghis_Capella", "nombres": "Genghis", "apellidos": "Capella"},
        }

        def mock_find_docente(cedula):
            if cedula == "19800720":
                return None  # Cédula real aún no existe
            if cedula == "Genghis_Capella":
                return provisional_doc  # Docente provisional existe
            return None

        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(side_effect=mock_find_docente)
        agent.mongo_service.update_cedula_provisional = MagicMock()
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()

        resultado = agent.process(result_rif_con_carpeta)

        assert resultado["exito"] is True
        assert resultado["docente_id"] == "prov_id_001"
        agent.mongo_service.update_cedula_provisional.assert_called_once_with(
            "Genghis_Capella", "19800720"
        )
        agent.mongo_service.insert_docente = MagicMock()
        agent.mongo_service.insert_docente.assert_not_called()

    def test_provisional_error_al_vincular_crea_docente_nuevo(self, fake_storage):
        """Si falla la actualización del provisional, se crea un docente nuevo."""
        from pymongo.errors import PyMongoError

        result_rif_con_carpeta = {
            **CLASSIFIED_RESULT_RIF,
            "carpeta_origen": "Genghis_Capella",
        }
        provisional_doc = {
            "_id": "prov_id_001",
            "docente": {"cedula": "Genghis_Capella"},
        }

        def mock_find_docente(cedula):
            if cedula == "19800720":
                return None
            if cedula == "Genghis_Capella":
                return provisional_doc
            return None

        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(side_effect=mock_find_docente)
        agent.mongo_service.update_cedula_provisional = MagicMock(
            side_effect=PyMongoError("fallo update")
        )
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000002")
        agent.mongo_service.insert_docente = MagicMock(return_value="nuevo_id")
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()

        resultado = agent.process(result_rif_con_carpeta)

        assert resultado["exito"] is True
        agent.mongo_service.insert_docente.assert_called_once()

    def test_rif_extrae_cedula_del_numero_rif(self, fake_storage):
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=MONGO_DOCENTE)
        resultado = agent.process(CLASSIFIED_RESULT_RIF)
        assert resultado["exito"] is True
        agent.mongo_service.find_docente_by_cedula.assert_called_once_with("19800720")

    def test_rif_extrae_cedula_corta(self, fake_storage):
        result_cedula_corta = {
            **CLASSIFIED_RESULT_RIF,
            "clasificacion": {
                **CLASSIFIED_RESULT_RIF["clasificacion"],
                "campos_extraidos": {
                    "nombre_titular": "Pedro González",
                    "numero_rif": "V-12345671",  # cédula=1234567 (7 dígitos, persona mayor)
                },
            },
        }
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=MONGO_DOCENTE)
        resultado = agent.process(result_cedula_corta)
        assert resultado["exito"] is True
        agent.mongo_service.find_docente_by_cedula.assert_called_once_with("1234567")

    def test_rif_sin_numero_rif_usa_carpeta_provisional(self, fake_storage):
        result_sin_rif = {
            **CLASSIFIED_RESULT_RIF,
            "carpeta_origen": "Juan_Perez",
            "clasificacion": {
                **CLASSIFIED_RESULT_RIF["clasificacion"],
                "campos_extraidos": {"nombre_titular": "Juan Pérez"},
            },
        }
        agent = fake_storage()
        agent.mongo_service.docentes = MagicMock()
        agent.mongo_service.docentes.find.return_value = []
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=MONGO_DOCENTE)
        resultado = agent.process(result_sin_rif)
        assert resultado["exito"] is True
        agent.mongo_service.find_docente_by_cedula.assert_called_once_with("Juan_Perez")

    def test_documento_duplicado_por_hash_retorna_skip(self, fake_storage):
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=MONGO_DOCUMENTO)
        resultado = agent.process(CLASSIFIED_RESULT_VALIDO)
        assert resultado["exito"] is False
        assert resultado["accion"] == "skip"

    def test_crea_docente_nuevo_si_no_existe(self, fake_storage):
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        insert_docente = MagicMock(return_value="nuevo_docente_id")
        agent.mongo_service.insert_docente = insert_docente
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()

        agent.process(CLASSIFIED_RESULT_VALIDO)

        insert_docente.assert_called_once()

    def test_usa_docente_existente_sin_crear(self, fake_storage):
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=MONGO_DOCENTE)
        insert_docente = MagicMock()
        agent.mongo_service.insert_docente = insert_docente
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()

        resultado = agent.process(CLASSIFIED_RESULT_VALIDO)

        insert_docente.assert_not_called()
        assert resultado["exito"] is True

    def test_error_mongo_no_mueve_archivo(self, fake_storage):
        """Si MongoDB falla, el archivo no debe moverse."""
        from pymongo.errors import PyMongoError
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(side_effect=PyMongoError("timeout"))
        move_mock = MagicMock()
        agent.file_service.move_to_storage = move_mock

        resultado = agent.process(CLASSIFIED_RESULT_VALIDO)

        assert resultado["exito"] is False
        move_mock.assert_not_called()

    def test_error_insert_docente_retorna_error(self, fake_storage):
        from pymongo.errors import PyMongoError
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        agent.mongo_service.insert_docente = MagicMock(side_effect=PyMongoError("dup key"))

        resultado = agent.process(CLASSIFIED_RESULT_VALIDO)

        assert resultado["exito"] is False
        assert resultado["accion"] == "error"

    def test_error_mover_archivo_no_afecta_resultado_mongo(self, fake_storage):
        """Si move falla, el documento en MongoDB ya está insertado."""
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        agent.mongo_service.insert_docente = MagicMock(return_value="did001")
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()
        agent.file_service.move_to_storage = MagicMock(side_effect=OSError("disco lleno"))

        resultado = agent.process(CLASSIFIED_RESULT_VALIDO)

        # El resultado tiene documento_id (fue insertado) aunque move falló
        assert resultado["documento_id"] == "doc001"

    def test_retorna_dict_con_claves_esperadas(self, fake_storage):
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        agent.mongo_service.insert_docente = MagicMock(return_value="did001")
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()

        resultado = agent.process(CLASSIFIED_RESULT_VALIDO)

        assert "exito" in resultado
        assert "accion" in resultado
        assert "docente_id" in resultado
        assert "documento_id" in resultado


class TestStorageAgentNormalizeCedula:
    def test_normaliza_con_prefijo_v_guion(self):
        agent = StorageAgent.__new__(StorageAgent)
        assert agent._normalize_cedula("V-12345678") == "12345678"

    def test_normaliza_con_prefijo_v_sin_guion(self):
        agent = StorageAgent.__new__(StorageAgent)
        assert agent._normalize_cedula("V12345678") == "12345678"

    def test_normaliza_solo_digitos(self):
        agent = StorageAgent.__new__(StorageAgent)
        assert agent._normalize_cedula("12345678") == "12345678"

    def test_normaliza_con_puntos(self):
        agent = StorageAgent.__new__(StorageAgent)
        assert agent._normalize_cedula("V-12.345.678") == "12345678"


class TestStorageAgentBuildDocenteData:
    def test_extrae_nombres_y_apellidos(self, fake_storage):
        agent = fake_storage()
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        datos = agent._build_docente_data(
            "12345678",
            {"nombre_titular": "María Elena García"},
            "Maria_Elena_Garcia",
        )
        assert datos["docente"]["cedula"] == "12345678"
        assert datos["docente"]["apellidos"] == "García"
        assert "María" in datos["docente"]["nombres"]

    def test_usa_carpeta_cuando_no_hay_nombre(self, fake_storage):
        agent = fake_storage()
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        datos = agent._build_docente_data("99999999", {}, "Juan_Perez")
        assert datos["docente"]["cedula"] == "99999999"


# ---------------------------------------------------------------------------
# Tests: Audit Log
# ---------------------------------------------------------------------------

class TestStorageAuditLog:
    def test_audit_documento_no_valido(self, fake_storage, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.storage_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )
        agent = fake_storage()
        agent.process(CLASSIFIED_RESULT_NO_VALIDO)

        assert len(audit_calls) == 1
        args, _ = audit_calls[0]
        assert args[0] == "storage"
        assert args[1] == "documento_no_valido"
        assert args[2] == "skip"

    def test_audit_sin_cedula_sin_carpeta(self, fake_storage, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.storage_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )
        result_sin_todo = {**CLASSIFIED_RESULT_SIN_CEDULA, "carpeta_origen": ""}
        agent = fake_storage()
        agent.mongo_service.docentes = MagicMock()
        agent.mongo_service.docentes.find.return_value = []
        agent.process(result_sin_todo)

        assert len(audit_calls) == 1
        args, _ = audit_calls[0]
        assert args[1] == "sin_cedula"
        assert args[2] == "error"

    def test_audit_documento_duplicado(self, fake_storage, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.storage_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=MONGO_DOCUMENTO)
        agent.process(CLASSIFIED_RESULT_VALIDO)

        assert any(a[0][1] == "documento_duplicado" for a in audit_calls)

    def test_audit_proceso_completo_genera_multiples_logs(self, fake_storage, monkeypatch):
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.storage_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=None)
        agent.mongo_service.generate_expediente_numero = MagicMock(return_value="EXP-2026-000001")
        agent.mongo_service.insert_docente = MagicMock(return_value="did001")
        agent.mongo_service.insert_documento = MagicMock(return_value="doc001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()

        agent.process(CLASSIFIED_RESULT_VALIDO)

        acciones = [a[0][1] for a in audit_calls]
        assert "docente_creado" in acciones
        assert "documento_insertado" in acciones
        assert "archivo_movido" in acciones

    def test_audit_error_mongo_incluye_detalle(self, fake_storage, monkeypatch):
        from pymongo.errors import PyMongoError
        audit_calls = []
        monkeypatch.setattr(
            "src.agents.storage_agent.audit_log",
            lambda *a, **kw: audit_calls.append((a, kw)),
        )
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(
            side_effect=PyMongoError("connection refused")
        )

        agent.process(CLASSIFIED_RESULT_VALIDO)

        assert len(audit_calls) == 1
        _, kwargs = audit_calls[0]
        detalle = json.loads(kwargs["detalle"])
        assert "error" in detalle
        assert "paso" in detalle


# ---------------------------------------------------------------------------
# Tests: MongoService.enriquecer_docente_desde_cv
# ---------------------------------------------------------------------------

class TestMongoServiceEnriquecerDesdeCV:
    def test_actualiza_email_y_telefono(self, fake_mongo_service):
        service = fake_mongo_service()
        campos = {
            "correo_electronico": "mgarcia@uneg.edu.ve",
            "telefono": "0424-1234567",
        }
        service.enriquecer_docente_desde_cv("12345678", campos)

        # Debe haber llamado update_one con $set para email y teléfono
        assert service.docentes.update_one.called
        call_args = service.docentes.update_one.call_args_list[0]
        update_op = call_args[0][1]
        assert "$set" in update_op
        assert update_op["$set"]["docente.contacto.email_personal"] == "mgarcia@uneg.edu.ve"
        assert update_op["$set"]["docente.contacto.telefono_principal"] == "0424-1234567"

    def test_agrega_formacion_academica(self, fake_mongo_service):
        service = fake_mongo_service()
        campos = {
            "titulo_academico": "Magíster en Educación",
            "institucion_emisora": "Universidad Central de Venezuela",
        }
        service.enriquecer_docente_desde_cv("12345678", campos)

        # Debe haber llamado update_one con $addToSet para formación
        assert service.docentes.update_one.called
        ultima_llamada = service.docentes.update_one.call_args_list[-1]
        update_op = ultima_llamada[0][1]
        assert "$addToSet" in update_op
        formacion = update_op["$addToSet"]["formacion_academica"]
        assert formacion["titulo_obtenido"] == "Magíster en Educación"
        assert formacion["institucion"] == "Universidad Central de Venezuela"

    def test_campos_vacios_no_llama_set(self, fake_mongo_service):
        service = fake_mongo_service()
        # Sin email ni teléfono → no debe llamar update_one para $set
        service.enriquecer_docente_desde_cv("12345678", {"titulo_academico": "Lic."})

        # Solo la llamada de $addToSet, nunca una de $set
        for call in service.docentes.update_one.call_args_list:
            assert "$set" not in call[0][1]

    def test_sin_titulo_no_llama_addtoset(self, fake_mongo_service):
        service = fake_mongo_service()
        service.enriquecer_docente_desde_cv("12345678", {"correo_electronico": "x@y.com"})

        for call in service.docentes.update_one.call_args_list:
            assert "$addToSet" not in call[0][1]

    def test_campos_vacios_no_hace_ninguna_llamada(self, fake_mongo_service):
        service = fake_mongo_service()
        service.enriquecer_docente_desde_cv("12345678", {})
        service.docentes.update_one.assert_not_called()

    def test_error_mongo_relanza_excepcion(self, fake_mongo_service):
        from pymongo.errors import PyMongoError
        service = fake_mongo_service()
        service.docentes.update_one.side_effect = PyMongoError("timeout")
        with pytest.raises(PyMongoError):
            service.enriquecer_docente_desde_cv("12345678", {"correo_electronico": "a@b.com"})

    def test_set_usa_condicion_null_para_no_sobreescribir(self, fake_mongo_service):
        """El filtro de update_one debe exigir que los campos sean None."""
        service = fake_mongo_service()
        campos = {"correo_electronico": "nuevo@mail.com"}
        service.enriquecer_docente_desde_cv("12345678", campos)

        filtro = service.docentes.update_one.call_args_list[0][0][0]
        # La condición debe incluir que el campo actual sea None
        assert filtro.get("docente.contacto.email_personal") is None


# ---------------------------------------------------------------------------
# Tests: StorageAgent — enriquecimiento desde CV
# ---------------------------------------------------------------------------

class TestStorageAgentEnriquecimientoCV:
    def _setup_agent_cv(self, fake_storage):
        """Configura un StorageAgent listo para procesar un curriculo_vitae."""
        agent = fake_storage()
        agent.mongo_service.find_documento_by_hash = MagicMock(return_value=None)
        agent.mongo_service.find_docente_by_cedula = MagicMock(return_value=MONGO_DOCENTE)
        agent.mongo_service.insert_documento = MagicMock(return_value="doc_cv_001")
        agent.mongo_service.update_completitud = MagicMock()
        agent.mongo_service.update_archivo_ruta = MagicMock()
        agent.mongo_service.enriquecer_docente_desde_cv = MagicMock()
        return agent

    def test_curriculo_vitae_llama_enriquecer(self, fake_storage):
        agent = self._setup_agent_cv(fake_storage)

        resultado = agent.process(CLASSIFIED_RESULT_CURRICULO_VITAE)

        assert resultado["exito"] is True
        agent.mongo_service.enriquecer_docente_desde_cv.assert_called_once_with(
            "12345678",
            CLASSIFIED_RESULT_CURRICULO_VITAE["clasificacion"]["campos_extraidos"],
        )

    def test_otro_tipo_no_llama_enriquecer(self, fake_storage):
        agent = self._setup_agent_cv(fake_storage)

        agent.process(CLASSIFIED_RESULT_VALIDO)  # tipo: titulo_universitario

        agent.mongo_service.enriquecer_docente_desde_cv.assert_not_called()

    def test_enriquecer_falla_proceso_continua_exitoso(self, fake_storage):
        """Si enriquecer_docente_desde_cv lanza excepción, el proceso no se interrumpe."""
        from pymongo.errors import PyMongoError
        agent = self._setup_agent_cv(fake_storage)
        agent.mongo_service.enriquecer_docente_desde_cv = MagicMock(
            side_effect=PyMongoError("error de escritura")
        )

        resultado = agent.process(CLASSIFIED_RESULT_CURRICULO_VITAE)

        assert resultado["exito"] is True
        assert resultado["documento_id"] == "doc_cv_001"

    def test_enriquecer_recibe_cedula_normalizada(self, fake_storage):
        """La cédula enviada a enriquecer debe estar normalizada (solo dígitos)."""
        agent = self._setup_agent_cv(fake_storage)
        result_cedula_prefijo = {
            **CLASSIFIED_RESULT_CURRICULO_VITAE,
            "clasificacion": {
                **CLASSIFIED_RESULT_CURRICULO_VITAE["clasificacion"],
                "campos_extraidos": {
                    **CLASSIFIED_RESULT_CURRICULO_VITAE["clasificacion"]["campos_extraidos"],
                    "cedula_titular": "V-12345678",
                },
            },
        }

        agent.process(result_cedula_prefijo)

        cedula_enviada = agent.mongo_service.enriquecer_docente_desde_cv.call_args[0][0]
        assert cedula_enviada == "12345678"
