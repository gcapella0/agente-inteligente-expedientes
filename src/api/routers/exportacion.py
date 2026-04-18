from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


@router.get("/{cedula}/exportar")
async def exportar_expediente(
    cedula: str,
    formato: str = Query("json", description="Formato de exportación (json|xml|csv)"),
    incluir_documentos: bool = Query(True, description="Incluir metadatos de documentos"),
    incluir_ocr: bool = Query(False, description="Incluir texto OCR completo"),
):
    """Exporta el expediente completo en el formato solicitado."""
    import json

    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Docente no encontrado para exportación: {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        docente["_id"] = str(docente["_id"])

        datos: dict = {
            "numero_expediente": docente.get("expediente_numero"),
            "docente": {
                "cedula": docente["docente"].get("cedula"),
                "nombres": docente["docente"].get("nombres"),
                "apellidos": docente["docente"].get("apellidos"),
                "fecha_nacimiento": str(docente["docente"].get("fecha_nacimiento"))
                if docente["docente"].get("fecha_nacimiento")
                else None,
            },
            "formacion_academica": docente.get("formacion_academica", []),
            "vinculacion_institucional": docente.get("vinculacion_institucional", {}),
            "completitud": docente.get("completitud", {}),
            "status": docente.get("status"),
            "created_at": str(docente.get("created_at")),
            "updated_at": str(docente.get("updated_at")),
        }

        if incluir_documentos:
            documentos = list(mongo.documentos.find({"docente_cedula": cedula}))
            datos["documentos"] = []
            for doc in documentos:
                doc_dict: dict = {
                    "_id": str(doc["_id"]),
                    "tipo": doc.get("tipo"),
                    "nombre": doc.get("nombre"),
                    "validacion": doc.get("validacion", {}),
                    "ocr": {
                        "procesado": doc.get("ocr", {}).get("procesado"),
                        "confianza_promedio": doc.get("ocr", {}).get("confianza_promedio"),
                    },
                }
                if incluir_ocr:
                    doc_dict["ocr"]["texto_completo"] = doc.get("ocr", {}).get("texto_completo", "")
                datos["documentos"].append(doc_dict)

        if formato == "json":
            contenido = json.dumps(datos, indent=2, default=str)
            return StreamingResponse(
                iter([contenido]),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename=expediente_{cedula}.json"},
            )

        if formato == "xml":
            xml = _dict_a_xml(datos)
            return StreamingResponse(
                iter([xml]),
                media_type="application/xml",
                headers={"Content-Disposition": f"attachment; filename=expediente_{cedula}.xml"},
            )

        if formato == "csv":
            csv_content = _dict_a_csv(datos)
            return StreamingResponse(
                iter([csv_content]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=expediente_{cedula}.csv"},
            )

        raise HTTPException(status_code=415, detail="Formato no soportado. Use json, xml o csv.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exportando expediente {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error en exportación")


def _dict_a_xml(datos: dict) -> str:
    """Convierte dict de expediente a XML simple."""

    def _nodo(clave: str, valor: object, nivel: int = 1) -> str:
        sangria = "  " * nivel
        if isinstance(valor, dict):
            interior = "".join(_nodo(k, v, nivel + 1) for k, v in valor.items())
            return f"{sangria}<{clave}>\n{interior}{sangria}</{clave}>\n"
        if isinstance(valor, list):
            items = "".join(
                _nodo("item", item, nivel + 1) if isinstance(item, dict)
                else f"{'  ' * (nivel + 1)}<item>{item}</item>\n"
                for item in valor
            )
            return f"{sangria}<{clave}>\n{items}{sangria}</{clave}>\n"
        return f"{sangria}<{clave}>{valor}</{clave}>\n"

    cuerpo = "".join(_nodo(k, v) for k, v in datos.items())
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<expediente>\n{cuerpo}</expediente>'


def _dict_a_csv(datos: dict) -> str:
    """Convierte dict de expediente a CSV (clave/valor aplanado)."""

    def _aplanar(d: object, prefijo: str = "") -> list[tuple[str, object]]:
        if isinstance(d, dict):
            filas: list[tuple[str, object]] = []
            for k, v in d.items():
                clave = f"{prefijo}.{k}" if prefijo else k
                filas.extend(_aplanar(v, clave))
            return filas
        if isinstance(d, list):
            return [(prefijo, len(d))]
        return [(prefijo, d)]

    salida = io.StringIO()
    writer = csv.writer(salida)
    writer.writerow(["campo", "valor"])
    for clave, valor in _aplanar(datos):
        writer.writerow([clave, valor])
    return salida.getvalue()
