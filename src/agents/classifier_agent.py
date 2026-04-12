"""Agente clasificador que usa un LLM para clasificar documentos procesados por OCR."""

from __future__ import annotations

import json
import time

from src.core.logger import audit_log, get_agent_logger
from src.services.llm_service import LlmService

logger = get_agent_logger("classifier")


class ClassifierAgent:
    """Agente que clasifica documentos usando LLM y extrae campos estructurados."""

    def __init__(self, llm_service: LlmService) -> None:
        self.llm_service = llm_service

    def classify(self, ocr_result: dict) -> dict:
        """Clasifica un resultado OCR mediante el LLM.

        Args:
            ocr_result: Diccionario generado por OcrAgent para un archivo,
                debe contener la clave ``ocr_resultado`` con el resultado OCR.

        Returns:
            Diccionario original enriquecido con la clave ``clasificacion``
            que contiene tipo, validez, campos extraídos y metadatos.
        """
        ocr_data = ocr_result.get("ocr_resultado")
        archivo = ocr_result.get("archivo_nombre", "desconocido")

        json_ligero = ocr_data.get("json_ligero") if ocr_data else None
        tiene_json_ligero = json_ligero and json_ligero.get("pages")
        tiene_texto = bool(ocr_data.get("texto_completo")) if ocr_data else False

        if not ocr_data or (not tiene_json_ligero and not tiene_texto):
            logger.warning(
                "Sin texto OCR para clasificar: '{}'", archivo
            )
            clasificacion = {
                "valido": False,
                "tipo": "no_valido",
                "razon_rechazo": "Sin texto OCR disponible para clasificar",
                "campos_extraidos": {},
                "confianza_clasificacion": 0.0,
                "modelo_llm": self.llm_service.model,
                "tokens_usados": 0,
            }
            audit_log(
                "classifier",
                "clasificacion_fallida",
                "error",
                archivo=archivo,
                detalle=json.dumps(
                    {"razon": "sin_texto_ocr"},
                    ensure_ascii=False,
                ),
            )
            return {**ocr_result, "clasificacion": clasificacion}

        if tiene_json_ligero:
            texto_para_llm = json.dumps(json_ligero, ensure_ascii=False)
        else:
            texto_para_llm = ocr_data["texto_completo"]

        logger.info("Clasificando documento: '{}'", archivo)
        inicio = time.perf_counter()

        try:
            resultado_llm = self.llm_service.classify_and_extract(texto_para_llm)
        except Exception as exc:
            tiempo_ms = round((time.perf_counter() - inicio) * 1000, 2)
            logger.error(
                "Error al clasificar '{}': {}", archivo, exc
            )
            clasificacion = {
                "valido": False,
                "tipo": "no_valido",
                "razon_rechazo": f"Error del LLM: {exc}",
                "campos_extraidos": {},
                "confianza_clasificacion": 0.0,
                "modelo_llm": self.llm_service.model,
                "tokens_usados": 0,
            }
            audit_log(
                "classifier",
                "clasificacion_fallida",
                "error",
                archivo=archivo,
                detalle=json.dumps(
                    {
                        "error": str(exc),
                        "modelo_llm": self.llm_service.model,
                        "tiempo_respuesta_ms": tiempo_ms,
                    },
                    ensure_ascii=False,
                ),
            )
            return {**ocr_result, "clasificacion": clasificacion}

        tiempo_ms = round((time.perf_counter() - inicio) * 1000, 2)

        clasificacion = {
            "valido": resultado_llm.get("valido", False),
            "tipo": resultado_llm.get("tipo", "no_valido"),
            "campos_extraidos": resultado_llm.get("campos_extraidos", {}),
            "confianza_clasificacion": resultado_llm.get(
                "confianza_clasificacion", 0.0
            ),
            "razon_rechazo": resultado_llm.get("razon_rechazo"),
            "modelo_llm": resultado_llm.get("modelo_llm", self.llm_service.model),
            "tokens_usados": resultado_llm.get("tokens_usados", 0),
        }

        detalle_audit = json.dumps(
            {
                "modelo_llm": clasificacion["modelo_llm"],
                "confianza_clasificacion": clasificacion["confianza_clasificacion"],
                "campos_extraidos_count": len(clasificacion["campos_extraidos"]),
                "tokens_usados": clasificacion["tokens_usados"],
                "tiempo_respuesta_ms": tiempo_ms,
            },
            ensure_ascii=False,
        )

        if clasificacion["valido"]:
            audit_log(
                "classifier",
                "clasificado",
                "ok",
                archivo=archivo,
                documento_tipo=clasificacion["tipo"],
                detalle=detalle_audit,
            )
            logger.info(
                "Clasificado '{}' como '{}' (confianza: {:.2%}, {} ms)",
                archivo,
                clasificacion["tipo"],
                clasificacion["confianza_clasificacion"] or 0.0,
                tiempo_ms,
            )
        else:
            audit_log(
                "classifier",
                "clasificado",
                "rechazado",
                archivo=archivo,
                documento_tipo=clasificacion["tipo"],
                detalle=detalle_audit,
            )
            logger.info(
                "Rechazado '{}': {} (confianza: {:.2%}, {} ms)",
                archivo,
                clasificacion.get("razon_rechazo", "sin razón"),
                clasificacion["confianza_clasificacion"] or 0.0,
                tiempo_ms,
            )

        return {**ocr_result, "clasificacion": clasificacion}
