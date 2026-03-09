"""Servicio OCR basado en docTR para procesamiento de documentos."""

from __future__ import annotations

from pathlib import Path

from doctr.io import DocumentFile
from doctr.models import ocr_predictor

from src.core.logger import get_agent_logger

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

logger = get_agent_logger("ocr")


class OcrService:
    """Servicio que encapsula el modelo docTR para extraer texto de PDFs e imágenes."""

    def __init__(self) -> None:
        logger.info("Inicializando modelo docTR (ocr_predictor)…")
        self.model = ocr_predictor(pretrained=True)
        logger.info("Modelo docTR inicializado correctamente")

    def process_file(self, file_path: Path) -> dict:
        """Ejecuta OCR sobre un archivo PDF o imagen y retorna resultados estructurados.

        Args:
            file_path: Ruta al archivo a procesar.

        Returns:
            Diccionario con texto_completo, json_export, confianza_promedio,
            paginas, idioma_detectado y palabras_detectadas.

        Raises:
            ValueError: Si la extensión del archivo no es soportada.
            Exception: Si docTR falla al procesar el archivo.
        """
        extension = file_path.suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Extensión '{extension}' no soportada. "
                f"Extensiones válidas: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        logger.info("Procesando archivo: {}", file_path.name)

        if extension == ".pdf":
            doc = DocumentFile.from_pdf(str(file_path))
        else:
            doc = DocumentFile.from_images([str(file_path)])

        result = self.model(doc)
        texto_completo = result.render()
        json_output = result.export()

        paginas = json_output.get("pages", [])
        idioma_detectado = "desconocido"
        if paginas:
            idioma_info = paginas[0].get("language", {})
            if isinstance(idioma_info, dict) and idioma_info.get("value"):
                idioma_detectado = idioma_info["value"]

        return {
            "texto_completo": texto_completo,
            "json_export": json_output,
            "confianza_promedio": self.calcular_confianza_promedio(json_output),
            "paginas": len(paginas),
            "idioma_detectado": idioma_detectado,
            "palabras_detectadas": self.contar_palabras(json_output),
        }

    @staticmethod
    def calcular_confianza_promedio(json_output: dict) -> float:
        """Calcula la confianza promedio de todas las palabras detectadas.

        Recorre pages > blocks > lines > words y promedia los valores de
        ``confidence``. Retorna 0.0 si no hay palabras.
        """
        confidences: list[float] = []
        for page in json_output.get("pages", []):
            for block in page.get("blocks", []):
                for line in block.get("lines", []):
                    for word in line.get("words", []):
                        confidences.append(word["confidence"])

        if not confidences:
            return 0.0
        return round(sum(confidences) / len(confidences), 4)

    @staticmethod
    def contar_palabras(json_output: dict) -> int:
        """Cuenta el total de palabras detectadas en todas las páginas."""
        total = 0
        for page in json_output.get("pages", []):
            for block in page.get("blocks", []):
                for line in block.get("lines", []):
                    total += len(line.get("words", []))
        return total
