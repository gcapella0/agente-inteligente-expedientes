from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
INPUT_DIR = Path(os.getenv("INPUT_DIR", DATA_DIR / "input"))
PROCESSED_UIDS_FILE = Path(
    os.getenv("PROCESSED_UIDS_FILE", DATA_DIR / "processed_uids.json")
)
LOG_DIR = Path(os.getenv("LOG_DIR", ROOT_DIR / "logs"))
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "60"))
REQUIRED_ENV_VARS = ("MAIL_USER", "MAIL_PASS", "MAIL_HOST")


def validate() -> None:
    """Valida que las variables de entorno críticas estén disponibles."""

    missing = [env for env in REQUIRED_ENV_VARS if not os.getenv(env)]
    if missing:
        raise EnvironmentError(
            f"Variables de entorno faltantes para el watcher: {', '.join(sorted(missing))}"
        )


def ensure_directories() -> None:
    """Crea los directorios requeridos por el servicio."""

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_UIDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

