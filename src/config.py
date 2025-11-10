"""Configuración del proyecto usando variables de entorno."""
import os
from dotenv import load_dotenv
from loguru import logger
from typing import Optional

# Cargar el archivo .env desde la raíz del proyecto
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
dotenv_path = os.path.join(BASE_DIR, ".env")

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    logger.info(f"Archivo .env cargado correctamente desde: {dotenv_path}")
else:
    logger.warning("⚠️ No se encontró el archivo .env en la raíz del proyecto.")


class Config:
    """Clase para gestionar la configuración del proyecto."""

    # Configuración de correo IMAP
    MAIL_HOST: Optional[str] = os.getenv("MAIL_HOST")
    MAIL_USER: Optional[str] = os.getenv("MAIL_USER")
    MAIL_PASS: Optional[str] = os.getenv("MAIL_PASS")
    MAIL_SSL: bool = os.getenv("MAIL_SSL", "true").lower() == "true"
    MAIL_FOLDER: str = os.getenv("MAIL_FOLDER", "INBOX")
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    # Rutas de datos
    DATA_DIR: str = os.path.join(BASE_DIR, "data")
    INPUT_DIR: str = os.path.join(DATA_DIR, "input")
    PROCESSED_UIDS_FILE: str = os.path.join(DATA_DIR, "processed_uids.json")

    @classmethod
    def validate(cls) -> None:
        """Valida que las variables de entorno requeridas estén configuradas."""
        if not all([cls.MAIL_HOST, cls.MAIL_USER, cls.MAIL_PASS]):
            raise ValueError("Variables de entorno faltantes: MAIL_HOST, MAIL_USER, MAIL_PASS")

    @classmethod
    def ensure_directories(cls) -> None:
        """Crea los directorios necesarios si no existen."""
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        os.makedirs(cls.INPUT_DIR, exist_ok=True)


# Instancia global de configuración
config = Config()

