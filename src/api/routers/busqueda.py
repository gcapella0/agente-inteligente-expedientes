from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")


@router.get("/buscar-texto")
async def buscar_texto(
    q: str = Query(..., min_length=2, description="Texto a buscar"),
    tipo: Optional[str] = Query(None, description="Filtrar por tipo de documento"),
    campos: Optional[str] = Query(None, description="Campos específicos a retornar (separados por coma)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Búsqueda full-text en OCR de documentos."""
    try:
        inicio = time.perf_counter()
        mongo = MongoService()

        filtro: dict = {"$text": {"$search": q}}
        if tipo:
            filtro["tipo"] = tipo

        proyeccion = {"score": {"$meta": "textScore"}}

        resultados = list(
            mongo.documentos.find(filtro, proyeccion)
            .sort([("score", {"$meta": "textScore"})])
            .skip(skip)
            .limit(limit)
        )

        filtro_total: dict = {"$text": {"$search": q}}
        if tipo:
            filtro_total["tipo"] = tipo
        total = mongo.documentos.count_documents(filtro_total)

        campos_list = [c.strip() for c in campos.split(",")] if campos else []

        items = []
        for doc in resultados:
            item: dict = {
                "_id": str(doc["_id"]),
                "docente_cedula": doc.get("docente_cedula"),
                "tipo": doc.get("tipo"),
                "nombre": doc.get("nombre"),
                "relevancia": round(doc.get("score", 0), 2),
            }
            if campos_list:
                campos_extraidos = doc.get("ocr", {}).get("campos_extraidos", {})
                for campo in campos_list:
                    if campo in campos_extraidos:
                        item[campo] = campos_extraidos[campo]
            items.append(item)

        # Enriquecer con nombre del docente
        cedulas = {item["docente_cedula"] for item in items if item["docente_cedula"]}
        docentes_map: dict = {}
        for cedula in cedulas:
            docente = mongo.docentes.find_one({"docente.cedula": cedula}, {"docente.nombres": 1, "docente.apellidos": 1})
            if docente:
                nombres = docente.get("docente", {}).get("nombres", "")
                apellidos = docente.get("docente", {}).get("apellidos", "")
                docentes_map[cedula] = f"{nombres} {apellidos}".strip()

        for item in items:
            cedula = item.get("docente_cedula")
            if cedula and cedula in docentes_map:
                item["docente_nombre"] = docentes_map[cedula]

        tiempo_ms = round((time.perf_counter() - inicio) * 1000, 1)
        logger.info(f"Búsqueda texto: q={q!r}, resultados={len(items)}, tiempo={tiempo_ms}ms")

        return {
            "query": q,
            "resultados": items,
            "total": total,
            "skip": skip,
            "limit": limit,
            "tiempo_busqueda_ms": tiempo_ms,
        }

    except Exception as e:
        logger.error(f"Error en búsqueda texto: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error en búsqueda")
