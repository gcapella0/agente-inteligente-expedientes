from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src import config
from src.api.dependencies import verify_token
from src.core.logger import get_agent_logger

router = APIRouter()
logger = get_agent_logger("api")

_OPERATIONAL_LOG = config.LOG_DIR / "operational.log"
_AUDIT_LOG = config.LOG_DIR / "audit.jsonl"
_KEEPALIVE_INTERVAL = 15.0  # segundos
_POLL_INTERVAL = 0.5        # segundos


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/stream")
async def stream_logs(
    agente: str | None = Query(None, description="Filtrar por nombre de agente"),
    nivel: str | None = Query(None, description="Filtrar por nivel: INFO, WARNING, ERROR"),
    payload: dict = Depends(verify_token),
):
    """SSE endpoint que tailea operational.log en tiempo real."""

    async def event_source():
        if not _OPERATIONAL_LOG.exists():
            # Archivo todavía no creado; mantener conexión hasta que aparezca
            while not _OPERATIONAL_LOG.exists():
                yield "event: keepalive\ndata: \n\n"
                await asyncio.sleep(_KEEPALIVE_INTERVAL)

        nivel_upper = nivel.upper() if nivel else None

        async with aiofiles.open(_OPERATIONAL_LOG, mode="r", encoding="utf-8") as f:
            await f.seek(0, 2)  # seek al final del archivo
            ultimo_keepalive = time.time()

            while True:
                line = await f.readline()
                if not line:
                    # Sin líneas nuevas: keepalive si toca
                    if time.time() - ultimo_keepalive >= _KEEPALIVE_INTERVAL:
                        yield "event: keepalive\ndata: \n\n"
                        ultimo_keepalive = time.time()
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line).get("record", {})
                except (json.JSONDecodeError, ValueError):
                    continue

                agente_registro = record.get("extra", {}).get("agent")
                nivel_registro = record.get("level", {}).get("name")

                if agente and agente_registro != agente:
                    continue
                if nivel_upper and nivel_registro != nivel_upper:
                    continue

                evento = {
                    "timestamp": record.get("time", {}).get("repr"),
                    "nivel": nivel_registro,
                    "agente": agente_registro,
                    "mensaje": record.get("message"),
                }
                yield f"event: log\ndata: {json.dumps(evento, ensure_ascii=False)}\n\n"
                ultimo_keepalive = time.time()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/descargar")
async def descargar_auditoria(payload: dict = Depends(verify_token)):
    """Descarga audit.jsonl como archivo adjunto."""
    if not _AUDIT_LOG.exists():
        raise HTTPException(status_code=404, detail="Archivo de auditoría no encontrado")

    filename = f"audit-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    logger.info("Descarga de auditoría solicitada por '{}'", payload.get("sub"))

    return StreamingResponse(
        _AUDIT_LOG.open("rb"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
