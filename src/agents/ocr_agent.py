"""Agente OCR que procesa documentos en data/input/ mediante docTR."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from src import config
from src.core.logger import audit_log, get_agent_logger
from src.services.ocr_service import SUPPORTED_EXTENSIONS, OcrService

logger = get_agent_logger("ocr")


class OcrAgent:
    """Agente que recorre subcarpetas de input y ejecuta OCR sobre PDFs e imágenes."""

    def __init__(self, ocr_service: OcrService) -> None:
        self.ocr_service = ocr_service

    def process_directory(
        self,
        directory: Path | None = None,
        skip_hashes: set[str] | None = None,
    ) -> list[dict]:
        """Escanea subcarpetas del directorio y procesa archivos con OCR.

        Args:
            directory: Directorio raíz a escanear. Por defecto usa
                ``config.INPUT_DIR``.
            skip_hashes: Conjunto de hashes SHA-256 de archivos ya procesados.
                Los archivos cuyo hash coincida se omiten sin ejecutar OCR.

        Returns:
            Lista de diccionarios con los resultados de OCR por archivo.
        """
        directory = directory or config.INPUT_DIR
        resultados: list[dict] = []

        if not directory.is_dir():
            logger.warning("El directorio de entrada no existe: {}", directory)
            return resultados

        subcarpetas = sorted(
            p for p in directory.iterdir() if p.is_dir()
        )
        logger.info(
            "Iniciando procesamiento OCR — {} subcarpetas encontradas en {}",
            len(subcarpetas),
            directory,
        )

        for subcarpeta in subcarpetas:
            archivos = sorted(
                f
                for f in subcarpeta.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
            )

            if not archivos:
                logger.debug(
                    "Sin archivos procesables en subcarpeta: {}", subcarpeta.name
                )
                continue

            logger.info(
                "Subcarpeta '{}': {} archivo(s) a procesar",
                subcarpeta.name,
                len(archivos),
            )

            for archivo in archivos:
                if skip_hashes:
                    file_hash = hashlib.sha256(archivo.read_bytes()).hexdigest()
                    if file_hash in skip_hashes:
                        logger.info(
                            "Omitido '{}': ya procesado (hash {}…)",
                            archivo.name,
                            file_hash[:12],
                        )
                        continue
                resultado = self._process_single_file(archivo, subcarpeta.name)
                resultados.append(resultado)

        logger.info(
            "Procesamiento OCR finalizado — {} archivo(s) procesados", len(resultados)
        )
        return resultados

    def _process_single_file(self, file_path: Path, carpeta_origen: str) -> dict:
        """Procesa un archivo individual con OCR y registra el resultado.

        Args:
            file_path: Ruta al archivo.
            carpeta_origen: Nombre de la subcarpeta de origen.

        Returns:
            Diccionario con metadatos del archivo y resultado OCR.
        """
        contenido = file_path.read_bytes()
        hash_sha256 = hashlib.sha256(contenido).hexdigest()
        formato = file_path.suffix.lower().lstrip(".")
        tamano_bytes = len(contenido)

        entry: dict = {
            "archivo_path": file_path,
            "archivo_nombre": file_path.name,
            "carpeta_origen": carpeta_origen,
            "formato": formato,
            "tamano_bytes": tamano_bytes,
            "hash_sha256": hash_sha256,
            "ocr_resultado": None,
        }

        inicio = time.perf_counter()

        try:
            ocr_resultado = self.ocr_service.process_file(file_path)
        except Exception as exc:
            tiempo_ms = round((time.perf_counter() - inicio) * 1000, 2)
            logger.error(
                "Error al procesar '{}': {}", file_path.name, exc
            )
            audit_log(
                "ocr",
                "ocr_fallido",
                "error",
                archivo=str(file_path),
                detalle=json.dumps(
                    {
                        "motor": "doctr",
                        "error": str(exc),
                        "tiempo_procesamiento_ms": tiempo_ms,
                    },
                    ensure_ascii=False,
                ),
            )
            return entry

        tiempo_ms = round((time.perf_counter() - inicio) * 1000, 2)

        entry["ocr_resultado"] = ocr_resultado

        audit_log(
            "ocr",
            "ocr_completado",
            "ok",
            archivo=str(file_path),
            detalle=json.dumps(
                {
                    "motor": "doctr",
                    "paginas": ocr_resultado["paginas"],
                    "confianza_promedio": ocr_resultado["confianza_promedio"],
                    "palabras_detectadas": ocr_resultado["palabras_detectadas"],
                    "tiempo_procesamiento_ms": tiempo_ms,
                },
                ensure_ascii=False,
            ),
        )

        logger.info(
            "OCR completado: '{}' — {} pág, {} palabras, confianza {:.2%}, {:.0f} ms",
            file_path.name,
            ocr_resultado["paginas"],
            ocr_resultado["palabras_detectadas"],
            ocr_resultado["confianza_promedio"],
            tiempo_ms,
        )

        return entry
