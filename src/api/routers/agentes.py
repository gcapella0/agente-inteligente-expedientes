from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.api.dependencies import verify_token
from src.core.logger import audit_log, get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

_AGENTES_VALIDOS = ["watcher", "ocr", "classifier", "storage"]
_ORDEN_PIPELINE = ["watcher", "ocr", "classifier", "storage"]
_MODOS_VALIDOS = {"independiente", "pipeline"}


def _get_agente_func(nombre: str):
    """Importa y retorna la función del agente en forma lazy."""
    import src.main as _main
    return {
        "watcher": _main.test_watcher,
        "ocr": _main.test_ocr,
        "classifier": _main.test_classifier,
        "storage": _main.test_storage,
    }[nombre]

_COL = "sistema_agentes_estado"
_PIPELINE_ID = "__pipeline__"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class EstadoAgente(BaseModel):
    nombre: str
    estado: Literal["idle", "running", "error"]
    ultimo_run: str | None
    total_procesados: int
    error_msg: str | None
    siguiente_en_pipeline: str | None


class ListaAgentesResponse(BaseModel):
    agentes: list[EstadoAgente]
    pipeline_activo: bool
    pipeline_paso_actual: str | None


class EjecutarResponse(BaseModel):
    mensaje: str
    agente: str
    modo: str
    id_ejecucion: str
    siguiente_agente: str | None


# ---------------------------------------------------------------------------
# Helpers MongoDB
# ---------------------------------------------------------------------------


def _estado_default(nombre: str) -> dict:
    return {
        "_id": nombre,
        "nombre": nombre,
        "estado": "idle",
        "ultimo_run": None,
        "total_procesados": 0,
        "error_msg": None,
        "id_ejecucion_actual": None,
    }


def _pipeline_default() -> dict:
    return {"_id": _PIPELINE_ID, "pipeline_activo": False, "pipeline_paso_actual": None}


def _get_col(mongo: MongoService):
    return mongo.db[_COL]


def _actualizar_estado(mongo: MongoService, nombre: str, estado: str, **kwargs) -> None:
    update: dict = {"estado": estado}
    update.update(kwargs)
    _get_col(mongo).update_one(
        {"_id": nombre},
        {"$set": update},
        upsert=True,
    )


def _marcar_pipeline(mongo: MongoService, activo: bool, paso: str | None = None) -> None:
    _get_col(mongo).update_one(
        {"_id": _PIPELINE_ID},
        {"$set": {"pipeline_activo": activo, "pipeline_paso_actual": paso}},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Función background: corre agentes en threadpool de FastAPI
# ---------------------------------------------------------------------------


def _ejecutar(nombre: str, modo: str, id_ejecucion: str) -> None:
    mongo = MongoService()
    if modo == "pipeline":
        idx = _ORDEN_PIPELINE.index(nombre)
        agentes_a_correr = _ORDEN_PIPELINE[idx:]
        _marcar_pipeline(mongo, activo=True, paso=nombre)
    else:
        agentes_a_correr = [nombre]

    for i, a in enumerate(agentes_a_correr):
        if modo == "pipeline":
            pipeline_doc = _get_col(mongo).find_one({"_id": _PIPELINE_ID})
            if pipeline_doc is not None and pipeline_doc.get("pipeline_activo") is False:
                logger.info("Pipeline detenido externamente — abortando antes de '{}'", a)
                return
        _actualizar_estado(mongo, a, "running", id_ejecucion_actual=id_ejecucion)
        if modo == "pipeline":
            _marcar_pipeline(mongo, activo=True, paso=a)
        try:
            _get_agente_func(a)()
            now_iso = datetime.now(timezone.utc).isoformat()
            doc_actual = _get_col(mongo).find_one({"_id": a}) or {}
            nuevo_total = doc_actual.get("total_procesados", 0) + 1
            _actualizar_estado(
                mongo, a, "idle",
                ultimo_run=now_iso,
                total_procesados=nuevo_total,
                error_msg=None,
                id_ejecucion_actual=None,
            )
        except Exception as exc:
            logger.error("Agente '{}' falló en ejecución {}: {}", a, id_ejecucion, exc)
            _actualizar_estado(mongo, a, "error", error_msg=str(exc), id_ejecucion_actual=None)
            if modo == "pipeline":
                _marcar_pipeline(mongo, activo=False, paso=None)
            return

        if modo == "pipeline" and i < len(agentes_a_correr) - 1:
            time.sleep(2)

    if modo == "pipeline":
        _marcar_pipeline(mongo, activo=False, paso=None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ListaAgentesResponse)
async def listar_agentes(payload: dict = Depends(verify_token)) -> dict:
    """Estado actual de cada agente y del pipeline."""
    try:
        mongo = MongoService()
        col = _get_col(mongo)

        docs = {d["_id"]: d for d in col.find({"_id": {"$in": _AGENTES_VALIDOS + [_PIPELINE_ID]}})}
        pipeline_doc = docs.get(_PIPELINE_ID, _pipeline_default())

        agentes = []
        for i, nombre in enumerate(_AGENTES_VALIDOS):
            d = docs.get(nombre, _estado_default(nombre))
            siguiente = _AGENTES_VALIDOS[i + 1] if i + 1 < len(_AGENTES_VALIDOS) else None
            agentes.append(EstadoAgente(
                nombre=nombre,
                estado=d.get("estado", "idle"),
                ultimo_run=d.get("ultimo_run"),
                total_procesados=d.get("total_procesados", 0),
                error_msg=d.get("error_msg"),
                siguiente_en_pipeline=siguiente,
            ))

        return {
            "agentes": agentes,
            "pipeline_activo": pipeline_doc.get("pipeline_activo", False),
            "pipeline_paso_actual": pipeline_doc.get("pipeline_paso_actual"),
        }
    except Exception as e:
        logger.error("Error listando agentes: {}", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al obtener estado de agentes")


@router.post("/{nombre}/ejecutar", status_code=status.HTTP_202_ACCEPTED, response_model=EjecutarResponse)
async def ejecutar_agente(
    nombre: str,
    background_tasks: BackgroundTasks,
    modo: str = Query("independiente"),
    payload: dict = Depends(verify_token),
) -> dict:
    """Dispara la ejecución manual de un agente."""
    if nombre not in _AGENTES_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Agente inválido '{nombre}'. Válidos: {_AGENTES_VALIDOS}",
        )
    if modo not in _MODOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Modo inválido '{modo}'. Válidos: {sorted(_MODOS_VALIDOS)}",
        )

    try:
        mongo = MongoService()
        col = _get_col(mongo)

        doc_agente = col.find_one({"_id": nombre})
        if doc_agente and doc_agente.get("estado") == "running":
            raise HTTPException(
                status_code=409,
                detail=f"El agente '{nombre}' ya está en ejecución.",
            )

        if modo == "pipeline":
            pipeline_doc = col.find_one({"_id": _PIPELINE_ID})
            if pipeline_doc and pipeline_doc.get("pipeline_activo"):
                paso_actual = pipeline_doc.get("pipeline_paso_actual", "desconocido")
                raise HTTPException(
                    status_code=409,
                    detail=f"Ya hay un pipeline activo (paso actual: '{paso_actual}'). Espera a que termine.",
                )

        id_ejecucion = uuid.uuid4().hex
        background_tasks.add_task(_ejecutar, nombre, modo, id_ejecucion)

        idx = _ORDEN_PIPELINE.index(nombre)
        siguiente = _ORDEN_PIPELINE[idx + 1] if modo == "pipeline" and idx + 1 < len(_ORDEN_PIPELINE) else None

        logger.info("Ejecución iniciada: agente='{}' modo='{}' id='{}'", nombre, modo, id_ejecucion)
        return {
            "mensaje": "Ejecución iniciada",
            "agente": nombre,
            "modo": modo,
            "id_ejecucion": id_ejecucion,
            "siguiente_agente": siguiente,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error iniciando agente '{}': {}", nombre, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al iniciar ejecución")


@router.post("/{nombre}/stop")
async def detener_agente(nombre: str, payload: dict = Depends(verify_token)) -> dict:
    """Marca un agente como detenido y limpia el estado del pipeline.

    No aborta una ejecución en curso (BackgroundTasks de Starlette no es cancelable),
    pero sí impide que el pipeline continúe al siguiente paso mediante el checkpoint en _ejecutar.
    """
    if nombre not in _AGENTES_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Agente inválido '{nombre}'. Válidos: {_AGENTES_VALIDOS}",
        )
    try:
        mongo = MongoService()
        _actualizar_estado(
            mongo, nombre, "idle",
            error_msg="Detenido por el usuario",
            id_ejecucion_actual=None,
        )
        _marcar_pipeline(mongo, activo=False, paso=None)
        audit_log("api", "stop_agente", "ok", detalle=f"agente={nombre}")
        logger.info("Agente '{}' detenido por solicitud del usuario", nombre)
        return {"exito": True, "agente": nombre, "estado": "detenido"}
    except Exception as e:
        logger.error("Error deteniendo agente '{}': {}", nombre, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al detener agente")
