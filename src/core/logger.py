"""Configuración de logging con loguru."""
import sys
from pathlib import Path
from loguru import logger

# Remover el handler por defecto
logger.remove()

# Configurar formato de logs
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# Agregar handler para consola
logger.add(
    sys.stdout,
    format=log_format,
    level="INFO",
    colorize=True,
)

# Agregar handler para archivo de logs
log_dir = Path(__file__).parent.parent.parent / "logs"
log_dir.mkdir(exist_ok=True)

logger.add(
    log_dir / "watcher_{time:YYYY-MM-DD}.log",
    format=log_format,
    level="DEBUG",
    rotation="00:00",
    retention="30 days",
    compression="zip",
    encoding="utf-8",
)

__all__ = ["logger"]

