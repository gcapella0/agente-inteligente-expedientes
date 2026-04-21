from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


@router.get("/expedientes")
async def estadisticas_expedientes(
    agrupar_por: str = Query("status", description="Agrupar por (status|departamento|completitud_rango|sede)"),
    intervalo: Optional[str] = Query(None, description="Intervalo temporal (dia|mes|trimestre|año)"),
):
    """Dashboard general de expedientes."""
    try:
        mongo = MongoService()

        if agrupar_por == "departamento":
            pipeline = [
                {
                    "$group": {
                        "_id": "$vinculacion_institucional.departamento",
                        "cantidad": {"$sum": 1},
                    }
                },
                {"$sort": {"cantidad": -1}},
            ]
        elif agrupar_por == "sede":
            pipeline = [
                {
                    "$group": {
                        "_id": "$vinculacion_institucional.sede",
                        "cantidad": {"$sum": 1},
                    }
                },
                {"$sort": {"cantidad": -1}},
            ]
        elif agrupar_por == "completitud_rango":
            pipeline = [
                {
                    "$group": {
                        "_id": {
                            "$cond": [
                                {"$lt": ["$completitud.porcentaje", 25]},
                                "0-25%",
                                {
                                    "$cond": [
                                        {"$lt": ["$completitud.porcentaje", 50]},
                                        "25-50%",
                                        {
                                            "$cond": [
                                                {"$lt": ["$completitud.porcentaje", 75]},
                                                "50-75%",
                                                "75-100%",
                                            ]
                                        },
                                    ]
                                },
                            ]
                        },
                        "cantidad": {"$sum": 1},
                    }
                },
                {"$sort": {"_id": 1}},
            ]
        else:
            # status (default) y cualquier valor no reconocido
            pipeline = [
                {"$group": {"_id": "$status", "cantidad": {"$sum": 1}}},
                {"$sort": {"cantidad": -1}},
            ]

        resultados = list(mongo.docentes.aggregate(pipeline))
        total_docentes = mongo.docentes.count_documents({})

        datos = []
        for item in resultados:
            porcentaje = round((item["cantidad"] / total_docentes * 100), 1) if total_docentes > 0 else 0
            datos.append({
                "categoria": item["_id"] or "Sin especificar",
                "cantidad": item["cantidad"],
                "porcentaje": porcentaje,
            })

        logger.info(f"Estadísticas expedientes: agrupar_por={agrupar_por}, total={total_docentes}")
        return {
            "timestamp": datetime.now(),
            "agrupacion": agrupar_por,
            "datos": datos,
            "total_docentes": total_docentes,
        }

    except Exception as e:
        logger.error(f"Error en estadísticas expedientes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error calculando estadísticas")


@router.get("/documentos")
async def estadisticas_documentos(
    tipo: Optional[str] = Query(None, description="Filtrar por tipo de documento"),
    estado_validacion: Optional[str] = Query(None, description="Filtrar por estado de validación"),
):
    """Análisis de documentos."""
    try:
        mongo = MongoService()

        filtro: dict = {}
        if tipo:
            filtro["tipo"] = tipo
        if estado_validacion:
            filtro["validacion.estado"] = estado_validacion

        # Tipos con menor presencia (excluye rechazados)
        pipeline_faltantes = [
            {"$match": {"validacion.estado": {"$ne": "rechazado"}}},
            {"$group": {"_id": "$tipo", "cantidad": {"$sum": 1}}},
            {"$sort": {"cantidad": 1}},
        ]
        faltantes = list(mongo.documentos.aggregate(pipeline_faltantes))[:10]

        # Documentos por estado de validación
        pipeline_estado = [
            {"$match": filtro},
            {"$group": {"_id": "$validacion.estado", "cantidad": {"$sum": 1}}},
            {"$sort": {"cantidad": -1}},
        ]
        por_estado = list(mongo.documentos.aggregate(pipeline_estado))
        por_estado_dict = {item["_id"]: item["cantidad"] for item in por_estado}

        # Estadísticas OCR
        total_docs = mongo.documentos.count_documents(filtro)
        procesados_ocr = mongo.documentos.count_documents({**filtro, "ocr.procesado": True})
        pendientes_ocr = total_docs - procesados_ocr

        pipeline_ocr = [
            {"$match": {**filtro, "ocr.procesado": True}},
            {"$group": {"_id": None, "confianza_promedio": {"$avg": "$ocr.confianza_promedio"}}},
        ]
        ocr_stats = list(mongo.documentos.aggregate(pipeline_ocr))
        confianza_promedio = ocr_stats[0]["confianza_promedio"] if ocr_stats else 0

        logger.info(f"Estadísticas documentos: tipo={tipo}, total={total_docs}")
        return {
            "filtros_aplicados": {"tipo": tipo, "estado_validacion": estado_validacion},
            "documento_faltante_top": [
                {"tipo": item["_id"], "cantidad_faltante": item["cantidad"]}
                for item in faltantes
            ],
            "documentos_por_estado": {
                "aprobado": por_estado_dict.get("aprobado", 0),
                "rechazado": por_estado_dict.get("rechazado", 0),
                "pendiente": por_estado_dict.get("pendiente", 0),
                "requiere_revision": por_estado_dict.get("requiere_revision", 0),
            },
            "procesamiento_ocr": {
                "procesados": procesados_ocr,
                "pendientes": pendientes_ocr,
                "tasa_confianza_promedio": round(confianza_promedio, 2) if confianza_promedio else 0,
            },
        }

    except Exception as e:
        logger.error(f"Error en estadísticas documentos: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error calculando estadísticas")


@router.get("/completitud")
async def estadisticas_completitud(
    rango_porcentaje: str = Query("0-25,25-50,50-75,75-100", description="Rangos de completitud"),
    agrupar_por: Optional[str] = Query(None, description="Agrupar por (departamento|sede|status)"),
):
    """Distribución de completitud de expedientes."""
    try:
        mongo = MongoService()

        rangos = [tuple(map(int, r.split("-"))) for r in rango_porcentaje.split(",")]

        distribucion: dict = {}
        for inicio, fin in rangos:
            filtro = (
                {"completitud.porcentaje": {"$gte": inicio, "$lt": fin}}
                if inicio < fin
                else {"completitud.porcentaje": {"$gte": inicio}}
            )
            cantidad = mongo.docentes.count_documents(filtro)
            distribucion[f"{inicio}-{fin}%"] = cantidad

        total = mongo.docentes.count_documents({})
        distribucion_final = {
            rango: {
                "cantidad": cantidad,
                "porcentaje_total": round((cantidad / total * 100), 1) if total > 0 else 0,
            }
            for rango, cantidad in distribucion.items()
        }

        por_departamento = []
        if agrupar_por in ("departamento", None):
            pipeline = [
                {
                    "$group": {
                        "_id": "$vinculacion_institucional.departamento",
                        "docentes": {"$sum": 1},
                        "promedio_completitud": {"$avg": "$completitud.porcentaje"},
                        "bajo_50": {
                            "$sum": {"$cond": [{"$lt": ["$completitud.porcentaje", 50]}, 1, 0]}
                        },
                    }
                },
                {"$sort": {"bajo_50": -1}},
            ]
            resultados = list(mongo.docentes.aggregate(pipeline))
            por_departamento = [
                {
                    "departamento": item["_id"] or "Sin especificar",
                    "docentes": item["docentes"],
                    "promedio_completitud": round(item["promedio_completitud"] or 0, 0),
                    "docentes_bajo_50%": item["bajo_50"],
                }
                for item in resultados
            ]

        total_bajo_50 = sum(dept["docentes_bajo_50%"] for dept in por_departamento)
        dept_critica = (
            max(por_departamento, key=lambda x: x["docentes_bajo_50%"])
            if por_departamento
            else None
        )
        if dept_critica and dept_critica["docentes_bajo_50%"] > 0:
            recomendacion = (
                f"Priorizar {dept_critica['departamento']}: "
                f"{dept_critica['docentes_bajo_50%']} docentes bajo 50%"
            )
        else:
            recomendacion = "Expedientes en buen estado general"

        logger.info(f"Estadísticas completitud: total_docentes={total}, bajo_50={total_bajo_50}")
        return {
            "distribucion_completitud": distribucion_final,
            "por_departamento": por_departamento,
            "recomendacion": recomendacion,
        }

    except Exception as e:
        logger.error(f"Error en estadísticas completitud: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error calculando estadísticas")
