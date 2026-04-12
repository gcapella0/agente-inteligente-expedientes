"""Servicio de gestión de archivos para el pipeline de expedientes."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from src import config
from src.core.logger import get_agent_logger

logger = get_agent_logger("storage")


class FileService:
    """Servicio de archivos: mover a storage, calcular hash y limpiar input."""

    @staticmethod
    def move_to_storage(
        source_path: Path,
        cedula: str,
        tipo_documento: str,
        fecha_emision: str | None,
    ) -> Path:
        """Mueve un archivo procesado a la carpeta de storage organizada.

        Args:
            source_path: Ruta actual del archivo en data/input/.
            cedula: Cédula del docente (sin prefijo V-).
            tipo_documento: Tipo de documento clasificado.
            fecha_emision: Fecha de emisión en formato YYYYMMDD o similar. Si es
                None se usa la fecha actual.

        Returns:
            Ruta destino donde quedó el archivo.

        Raises:
            OSError: Si ocurre un error de I/O al mover el archivo.
        """
        fecha = fecha_emision if fecha_emision else datetime.now().strftime("%Y%m%d")
        extension = source_path.suffix.lower()
        nombre_base = f"{tipo_documento}_{fecha}{extension}"

        destino_dir = config.STORAGE_DIR / cedula
        destino_dir.mkdir(parents=True, exist_ok=True)

        destino = destino_dir / nombre_base
        contador = 1
        while destino.exists():
            destino = destino_dir / f"{tipo_documento}_{fecha}_{contador}{extension}"
            contador += 1

        try:
            shutil.move(str(source_path), str(destino))
            logger.info(
                "Archivo movido a storage: {} → {}",
                source_path.name,
                destino,
            )
            return destino
        except OSError as exc:
            logger.error(
                "Error al mover archivo {} a {}: {}",
                source_path,
                destino,
                exc,
            )
            raise

    @staticmethod
    def compute_hash(file_path: Path) -> str:
        """Calcula el hash SHA-256 del contenido de un archivo.

        Args:
            file_path: Ruta al archivo.

        Returns:
            Hash SHA-256 en formato hexadecimal.

        Raises:
            OSError: Si el archivo no existe o no se puede leer.
        """
        sha256 = hashlib.sha256()
        try:
            with file_path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except OSError as exc:
            logger.error("Error al calcular hash de {}: {}", file_path, exc)
            raise

    @staticmethod
    def cleanup_input_directory(directory: Path) -> int:
        """Elimina todos los archivos de un directorio y lo borra si queda vacío.

        Args:
            directory: Directorio a limpiar (normalmente data/input/{docente}/).

        Returns:
            Cantidad de archivos eliminados.
        """
        if not directory.exists():
            logger.warning("Directorio no existe para limpieza: {}", directory)
            return 0

        eliminados = 0
        try:
            for archivo in directory.iterdir():
                if archivo.is_file():
                    archivo.unlink()
                    eliminados += 1
                    logger.debug("Archivo eliminado de input: {}", archivo.name)

            # Eliminar directorio si quedó vacío
            remaining = list(directory.iterdir())
            if not remaining:
                directory.rmdir()
                logger.info("Directorio de input eliminado (vacío): {}", directory)
        except OSError as exc:
            logger.error(
                "Error durante limpieza del directorio {}: {}",
                directory,
                exc,
            )

        logger.info(
            "Limpieza completada: {} archivo(s) eliminados de {}",
            eliminados,
            directory,
        )
        return eliminados
