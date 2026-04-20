"""Tests para la API Fase 2 — sin MongoDB real (todo mockeado)."""
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
# Datos de prueba
# ---------------------------------------------------------------------------

_CEDULA = "12345678"

_DOCENTE_DOC = {
    "_id": ObjectId(),
    "expediente_numero": "EXP-2026-000001",
    "status": "activo",
    "docente": {
        "cedula": _CEDULA,
        "nombres": "Juan",
        "apellidos": "Pérez",
        "contacto": {
            "email_personal": "juan@mail.com",
            "telefono_principal": "0424-1234567",
        },
        "direccion": {"direccion_completa": "Calle 1, Ciudad Guayana"},
    },
    "vinculacion_institucional": {"departamento": "Informática", "sede": "Caracas"},
    "completitud": {"porcentaje": 50},
    "updated_at": None,
}

_DOCUMENTO_DOC = {
    "_id": ObjectId(),
    "tipo": "cedula_identidad",
    "docente_cedula": _CEDULA,
    "validacion": {"estado": "aprobado"},
    "archivo": {"formato": "pdf", "tamano_bytes": 500_000},
    "ocr": {
        "procesado": True,
        "confianza_promedio": 0.95,
        "idioma_detectado": "es",
    },
    "created_at": None,
    "updated_at": None,
}


# ---------------------------------------------------------------------------
# TestEstadisticasExpedientes
# ---------------------------------------------------------------------------

class TestEstadisticasExpedientes:
    def _mock_mongo(self, aggregate_result=None, total=3):
        mongo = MagicMock()
        mongo.docentes.aggregate.return_value = iter(aggregate_result or [])
        mongo.docentes.count_documents.return_value = total
        return mongo

    def test_por_status(self):
        resultado = [{"_id": "activo", "cantidad": 3}]
        mongo = self._mock_mongo(aggregate_result=resultado, total=3)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes?agrupar_por=status")
        assert r.status_code == 200
        data = r.json()
        assert "datos" in data
        assert "total_docentes" in data
        assert data["agrupacion"] == "status"
        assert data["total_docentes"] == 3
        assert data["datos"][0]["categoria"] == "activo"
        assert data["datos"][0]["cantidad"] == 3
        assert data["datos"][0]["porcentaje"] == 100.0

    def test_por_departamento(self):
        resultado = [{"_id": "Informática", "cantidad": 5}]
        mongo = self._mock_mongo(aggregate_result=resultado, total=5)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes?agrupar_por=departamento")
        assert r.status_code == 200
        data = r.json()
        assert data["agrupacion"] == "departamento"
        assert len(data["datos"]) == 1

    def test_por_sede(self):
        resultado = [{"_id": "Caracas", "cantidad": 2}]
        mongo = self._mock_mongo(aggregate_result=resultado, total=2)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes?agrupar_por=sede")
        assert r.status_code == 200
        assert r.json()["agrupacion"] == "sede"

    def test_por_completitud_rango(self):
        resultado = [{"_id": "0-25%", "cantidad": 1}, {"_id": "50-75%", "cantidad": 2}]
        mongo = self._mock_mongo(aggregate_result=resultado, total=3)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes?agrupar_por=completitud_rango")
        assert r.status_code == 200
        assert r.json()["agrupacion"] == "completitud_rango"

    def test_agrupacion_invalida_usa_status(self):
        resultado = [{"_id": "activo", "cantidad": 1}]
        mongo = self._mock_mongo(aggregate_result=resultado, total=1)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes?agrupar_por=invalido")
        assert r.status_code == 200

    def test_categoria_none_reemplazada(self):
        resultado = [{"_id": None, "cantidad": 2}]
        mongo = self._mock_mongo(aggregate_result=resultado, total=2)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes")
        assert r.status_code == 200
        assert r.json()["datos"][0]["categoria"] == "Sin especificar"

    def test_sin_docentes(self):
        mongo = self._mock_mongo(aggregate_result=[], total=0)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes")
        assert r.status_code == 200
        assert r.json()["total_docentes"] == 0
        assert r.json()["datos"] == []

    def test_timestamp_presente(self):
        mongo = self._mock_mongo()
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/expedientes")
        assert "timestamp" in r.json()


# ---------------------------------------------------------------------------
# TestEstadisticasDocumentos
# ---------------------------------------------------------------------------

class TestEstadisticasDocumentos:
    def _mock_mongo(
        self,
        faltantes=None,
        por_estado=None,
        ocr_stats=None,
        total=5,
        procesados_ocr=3,
    ):
        mongo = MagicMock()
        # aggregate se llama 3 veces: faltantes, por_estado, ocr_stats
        mongo.documentos.aggregate.side_effect = [
            iter(faltantes or []),
            iter(por_estado or []),
            iter(ocr_stats or []),
        ]
        # count_documents se llama 2 veces: total y procesados_ocr
        mongo.documentos.count_documents.side_effect = [total, procesados_ocr]
        return mongo

    def test_sin_filtros(self):
        mongo = self._mock_mongo(
            faltantes=[{"_id": "rif", "cantidad": 1}],
            por_estado=[{"_id": "aprobado", "cantidad": 4}, {"_id": "pendiente", "cantidad": 1}],
            ocr_stats=[{"_id": None, "confianza_promedio": 0.9}],
        )
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/documentos")
        assert r.status_code == 200
        data = r.json()
        assert "documento_faltante_top" in data
        assert "documentos_por_estado" in data
        assert "procesamiento_ocr" in data

    def test_documentos_por_estado_completo(self):
        por_estado = [
            {"_id": "aprobado", "cantidad": 3},
            {"_id": "rechazado", "cantidad": 1},
            {"_id": "pendiente", "cantidad": 2},
            {"_id": "requiere_revision", "cantidad": 1},
        ]
        mongo = self._mock_mongo(por_estado=por_estado)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/documentos")
        estados = r.json()["documentos_por_estado"]
        assert estados["aprobado"] == 3
        assert estados["rechazado"] == 1
        assert estados["pendiente"] == 2
        assert estados["requiere_revision"] == 1

    def test_ocr_stats(self):
        mongo = self._mock_mongo(
            ocr_stats=[{"_id": None, "confianza_promedio": 0.87}],
            total=10,
            procesados_ocr=7,
        )
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/documentos")
        ocr = r.json()["procesamiento_ocr"]
        assert ocr["procesados"] == 7
        assert ocr["pendientes"] == 3
        assert ocr["tasa_confianza_promedio"] == 0.87

    def test_con_filtro_tipo(self):
        mongo = self._mock_mongo()
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/documentos?tipo=cedula_identidad")
        assert r.status_code == 200
        assert r.json()["filtros_aplicados"]["tipo"] == "cedula_identidad"

    def test_con_filtro_estado_validacion(self):
        mongo = self._mock_mongo()
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/documentos?estado_validacion=aprobado")
        assert r.status_code == 200
        assert r.json()["filtros_aplicados"]["estado_validacion"] == "aprobado"

    def test_sin_ocr_stats(self):
        mongo = self._mock_mongo(ocr_stats=[])
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/documentos")
        assert r.json()["procesamiento_ocr"]["tasa_confianza_promedio"] == 0


# ---------------------------------------------------------------------------
# TestEstadisticasCompletitud
# ---------------------------------------------------------------------------

class TestEstadisticasCompletitud:
    def _mock_mongo(self, counts=None, aggregate_result=None):
        mongo = MagicMock()
        # count_documents: 4 rangos + 1 total
        mongo.docentes.count_documents.side_effect = counts or [5, 3, 2, 1, 11]
        mongo.docentes.aggregate.return_value = iter(aggregate_result or [])
        return mongo

    def test_distribucion_por_defecto(self):
        mongo = self._mock_mongo()
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/completitud")
        assert r.status_code == 200
        data = r.json()
        assert "distribucion_completitud" in data
        assert "por_departamento" in data
        assert "recomendacion" in data

    def test_rangos_presentes_en_distribucion(self):
        mongo = self._mock_mongo()
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/completitud")
        dist = r.json()["distribucion_completitud"]
        assert "0-25%" in dist
        assert "25-50%" in dist
        assert "50-75%" in dist
        assert "75-100%" in dist

    def test_porcentaje_calculado(self):
        # 4 rangos: [5,3,2,1], total=11
        mongo = self._mock_mongo(counts=[5, 3, 2, 1, 11])
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/completitud")
        dist = r.json()["distribucion_completitud"]
        assert dist["0-25%"]["cantidad"] == 5
        assert dist["0-25%"]["porcentaje_total"] == round(5 / 11 * 100, 1)

    def test_con_agrupacion_departamento(self):
        resultados = [
            {
                "_id": "Informática",
                "docentes": 10,
                "promedio_completitud": 45.0,
                "bajo_50": 6,
            }
        ]
        mongo = self._mock_mongo(aggregate_result=resultados)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/completitud?agrupar_por=departamento")
        assert r.status_code == 200
        dept = r.json()["por_departamento"]
        assert len(dept) == 1
        assert dept[0]["departamento"] == "Informática"
        assert dept[0]["docentes_bajo_50%"] == 6

    def test_recomendacion_dept_critica(self):
        resultados = [{"_id": "Ciencias", "docentes": 8, "promedio_completitud": 30.0, "bajo_50": 7}]
        mongo = self._mock_mongo(aggregate_result=resultados)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/completitud")
        assert "Ciencias" in r.json()["recomendacion"]

    def test_recomendacion_buen_estado(self):
        resultados = [{"_id": "Matemáticas", "docentes": 5, "promedio_completitud": 90.0, "bajo_50": 0}]
        mongo = self._mock_mongo(aggregate_result=resultados)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/completitud")
        assert "buen estado" in r.json()["recomendacion"]

    def test_departamento_none_reemplazado(self):
        resultados = [{"_id": None, "docentes": 2, "promedio_completitud": 40.0, "bajo_50": 2}]
        mongo = self._mock_mongo(aggregate_result=resultados)
        with patch("src.api.routers.estadisticas.MongoService", return_value=mongo):
            r = client.get("/estadisticas/completitud")
        dept = r.json()["por_departamento"]
        assert dept[0]["departamento"] == "Sin especificar"


# ---------------------------------------------------------------------------
# TestValidacionExpediente
# ---------------------------------------------------------------------------

class TestValidacionExpediente:
    def _mock_mongo(self, docente=None, documentos=None):
        mongo = MagicMock()
        mongo.docentes.find_one.return_value = docente
        mongo.documentos.find.return_value = iter(documentos or [])
        return mongo

    def test_no_existe(self):
        mongo = self._mock_mongo(docente=None)
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get("/validacion/expediente/99999999")
        assert r.status_code == 404

    def test_estructura_respuesta(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        mongo = self._mock_mongo(docente=doc_docente, documentos=[dict(_DOCUMENTO_DOC)])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        assert r.status_code == 200
        data = r.json()
        assert "validaciones" in data
        assert "estado_general" in data
        assert "alertas" in data
        assert "es_apto_para_presentacion" in data
        assert data["docente_cedula"] == _CEDULA

    def test_documentos_requeridos_presentes(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        mongo = self._mock_mongo(docente=doc_docente, documentos=[dict(_DOCUMENTO_DOC)])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        docs_req = r.json()["validaciones"]["documentos_requeridos"]
        assert "cedula_identidad" in docs_req
        assert docs_req["cedula_identidad"]["presente"] is True
        assert docs_req["cedula_identidad"]["estado_validacion"] == "aprobado"

    def test_alerta_documento_faltante(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        # Solo cedula_identidad presente → los otros 9 generan alertas
        mongo = self._mock_mongo(docente=doc_docente, documentos=[dict(_DOCUMENTO_DOC)])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        alertas = r.json()["alertas"]
        assert any("partida_nacimiento" in a for a in alertas)
        assert any("rif" in a for a in alertas)

    def test_estado_general_critico(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        doc_docente["completitud"] = {"porcentaje": 10}
        mongo = self._mock_mongo(docente=doc_docente, documentos=[])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        assert r.json()["estado_general"] == "critico"

    def test_estado_general_requiere_atencion(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        doc_docente["completitud"] = {"porcentaje": 60}
        mongo = self._mock_mongo(docente=doc_docente, documentos=[])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        assert r.json()["estado_general"] == "requiere_atencion"

    def test_es_apto_false_incompleto(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        doc_docente["completitud"] = {"porcentaje": 50}
        mongo = self._mock_mongo(docente=doc_docente, documentos=[dict(_DOCUMENTO_DOC)])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        assert r.json()["es_apto_para_presentacion"] is False

    def test_ocr_completeness(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        doc_con_ocr = dict(_DOCUMENTO_DOC)  # procesado=True, confianza=0.95
        mongo = self._mock_mongo(docente=doc_docente, documentos=[doc_con_ocr])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        ocr = r.json()["validaciones"]["ocr_completeness"]
        assert ocr["documentos_procesados_ocr"] == 1
        assert ocr["documentos_pendientes_ocr"] == 0
        assert ocr["confianza_promedio"] == 0.95

    def test_integridad_datos(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        mongo = self._mock_mongo(docente=doc_docente)
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        integridad = r.json()["validaciones"]["integridad_datos"]
        assert integridad["email_principal_presente"] is True
        assert integridad["telefono_presente"] is True
        assert integridad["direccion_completa"] is True

    def test_alerta_sin_telefono(self):
        doc_docente = dict(_DOCENTE_DOC)
        doc_docente["_id"] = ObjectId()
        doc_docente["docente"]["contacto"] = {"email_personal": "x@mail.com"}
        mongo = self._mock_mongo(docente=doc_docente, documentos=[])
        with patch("src.api.routers.validacion.MongoService", return_value=mongo):
            r = client.get(f"/validacion/expediente/{_CEDULA}")
        alertas = r.json()["alertas"]
        assert any("Teléfono" in a for a in alertas)
