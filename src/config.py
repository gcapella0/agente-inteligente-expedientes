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

# --- OCR / Storage / API ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "expedientes_uneg")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", DATA_DIR / "storage"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "minimax/minimax-m2.5:free")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

_FALLBACK_MODELS_DEFAULT = (
    "minimax/minimax-m2.5:free,"
    "google/gemma-3-27b-it:free,"
    "meta-llama/llama-4-scout:free,"
    "qwen/qwen3-8b:free"
)
OPENROUTER_FALLBACK_MODELS: list[str] = [
    m.strip()
    for m in os.getenv("OPENROUTER_FALLBACK_MODELS", _FALLBACK_MODELS_DEFAULT).split(",")
    if m.strip()
]
AUDIT_RETENTION = os.getenv("AUDIT_RETENTION", "90 days")
AUDIT_ROTATION = os.getenv("AUDIT_ROTATION", "50 MB")


def validate() -> None:
    """Valida que las variables de entorno críticas del watcher estén disponibles."""

    missing = [env for env in REQUIRED_ENV_VARS if not os.getenv(env)]
    if missing:
        raise EnvironmentError(
            f"Variables de entorno faltantes para el watcher: {', '.join(sorted(missing))}"
        )


def validate_ocr() -> None:
    """Valida variables de entorno requeridas por los agentes OCR y storage."""

    required = ("MONGO_URI", "OPENROUTER_API_KEY")
    missing = [env for env in required if not os.getenv(env)]
    if missing:
        raise EnvironmentError(
            f"Variables de entorno faltantes para OCR/storage: {', '.join(sorted(missing))}"
        )


def ensure_directories() -> None:
    """Crea los directorios requeridos por el servicio."""

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_UIDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

