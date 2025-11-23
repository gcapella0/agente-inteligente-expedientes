from __future__ import annotations

import os
import sys

from loguru import logger

from src import config

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_ROTATION = os.getenv("LOG_ROTATION", "10 MB")
LOG_RETENTION = os.getenv("LOG_RETENTION", "14 days")

config.LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    colorize=True,
    diagnose=True,
    backtrace=True,
    enqueue=True,
)
logger.add(
    config.LOG_DIR / "watcher.log",
    level=LOG_LEVEL,
    rotation=LOG_ROTATION,
    retention=LOG_RETENTION,
    encoding="utf-8",
    enqueue=True,
)

__all__ = ["logger"]

