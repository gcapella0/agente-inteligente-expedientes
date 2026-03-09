from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from loguru import logger

from src import config

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_ROTATION = os.getenv("LOG_ROTATION", "10 MB")
LOG_RETENTION = os.getenv("LOG_RETENTION", "14 days")

config.LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Sink principal: stdout
# ---------------------------------------------------------------------------
logger.remove()
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    colorize=True,
    diagnose=True,
    backtrace=True,
    enqueue=True,
)

# ---------------------------------------------------------------------------
# Sink del watcher (existente)
# ---------------------------------------------------------------------------
logger.add(
    config.LOG_DIR / "watcher.log",
    level=LOG_LEVEL,
    rotation=LOG_ROTATION,
    retention=LOG_RETENTION,
    encoding="utf-8",
    enqueue=True,
)

# ---------------------------------------------------------------------------
# Sink de auditoría: logs/audit.jsonl  (JSON serializado por línea)
# ---------------------------------------------------------------------------
logger.add(
    config.LOG_DIR / "audit.jsonl",
    level="INFO",
    serialize=True,
    filter=lambda record: record["extra"].get("audit", False),
    rotation=config.AUDIT_ROTATION,
    retention=config.AUDIT_RETENTION,
    encoding="utf-8",
    enqueue=True,
)

# ---------------------------------------------------------------------------
# Sinks individuales por agente
# ---------------------------------------------------------------------------
_AGENT_LOGS = ("ocr", "classifier", "storage", "api")

for _agent_name in _AGENT_LOGS:
    logger.add(
        config.LOG_DIR / f"{_agent_name}.log",
        level=LOG_LEVEL,
        filter=lambda record, name=_agent_name: record["extra"].get("agent") == name,
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        encoding="utf-8",
        enqueue=True,
    )


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------
def audit_log(
    agente: str,
    accion: str,
    resultado: str,
    *,
    cedula: str | None = None,
    documento_tipo: str | None = None,
    archivo: str | None = None,
    detalle: str | None = None,
) -> None:
    """Registra un evento de auditoría estructurado en audit.jsonl."""

    logger.bind(
        audit=True,
        agent=agente,
        cedula=cedula,
        documento_tipo=documento_tipo,
        archivo=archivo,
        detalle=detalle,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    ).info("[{agente}] {accion}: {resultado}", agente=agente, accion=accion, resultado=resultado)


def get_agent_logger(agent_name: str):
    """Retorna un logger vinculado al agente especificado."""

    return logger.bind(agent=agent_name)


__all__ = ["logger", "audit_log", "get_agent_logger"]
