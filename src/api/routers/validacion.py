from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

_DOCUMENTOS_REQUERIDOS = [
    "cedula_identidad",
    "partida_nacimiento",
    "rif",
    "titulo_bachiller",
    "certificado_notas_bachillerato",
    "titulo_universitario",
    "certificado_notas_pregrado",
    "fondo_negro_titulo",
    "acta_grado",
    "resolucion_nombramiento",
]


@router.get("/expediente/{cedula}")
async def validar_expediente(
    cedula: str,
    detalle: bool = Query(False, description="Incluir detalles completos"),
):
    """Auditoría de validación de expediente."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Docente no encontrado para validación: {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        documentos = list(mongo.documentos.find({"docente_cedula": cedula}))

        # Validaciones por documento requerido
        tipos_presentes = {d["tipo"] for d in documentos}
        docs_requeridos: dict = {}
        for doc_type in _DOCUMENTOS_REQUERIDOS:
            presente = doc_type in tipos_presentes
            doc_obj = next((d for d in documentos if d["tipo"] == doc_type), None)
            docs_requeridos[doc_type] = {
                "presente": presente,
                "estado_validacion": doc_obj.get("validacion", {}).get("estado", "N/A") if doc_obj else "N/A",
                "observaciones": doc_obj.get("validacion", {}).get("observaciones") if doc_obj else None,
            }

        # Integridad de datos del docente
        contacto = docente.get("docente", {}).get("contacto", {}) or {}
        direccion = docente.get("docente", {}).get("direccion", {}) or {}
        integridad = {
            "campos_contacto_validos": bool(contacto),
            "email_principal_presente": bool(contacto.get("email_personal")),
            "telefono_presente": bool(contacto.get("telefono_principal")),
            "direccion_completa": bool(direccion.get("direccion_completa")),
        }

        # Completitud OCR
        docs_con_ocr = sum(1 for d in documentos if d.get("ocr", {}).get("procesado"))
        docs_sin_ocr = len(documentos) - docs_con_ocr
        confianza_sum = sum(
            d.get("ocr", {}).get("confianza_promedio", 0)
            for d in documentos
            if d.get("ocr", {}).get("procesado")
        )
        ocr_completeness = {
            "documentos_procesados_ocr": docs_con_ocr,
            "documentos_pendientes_ocr": docs_sin_ocr,
            "confianza_promedio": round(confianza_sum / docs_con_ocr, 2) if docs_con_ocr > 0 else 0,
        }

        # Alertas
        alertas = []
        for doc_type, info in docs_requeridos.items():
            if not info["presente"]:
                alertas.append(f"Documento faltante: {doc_type}")
        if not integridad["telefono_presente"]:
            alertas.append("Teléfono no registrado")
        if not integridad["direccion_completa"]:
            alertas.append("Dirección incompleta")

        # Estado general
        completitud = docente.get("completitud", {}).get("porcentaje", 0)
        es_apto = completitud >= 100 and len(alertas) == 0
        estado_general = "apto" if es_apto else ("requiere_atencion" if completitud >= 50 else "critico")

        logger.info(f"Validación expediente: {cedula}, estado={estado_general}, alertas={len(alertas)}")
        return {
            "docente_cedula": cedula,
            "validaciones": {
                "documentos_requeridos": docs_requeridos,
                "integridad_datos": integridad,
                "ocr_completeness": ocr_completeness,
            },
            "estado_general": estado_general,
            "alertas": alertas,
            "es_apto_para_presentacion": es_apto,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validando expediente {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error en validación")
