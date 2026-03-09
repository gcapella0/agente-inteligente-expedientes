from src.agents.watcher_agent import WatcherAgent
from src.core.logger import logger


def main() -> None:
    """
    Punto de entrada del servicio de Watcher.

    Ejecuta el WatcherAgent en modo continuo.
    """

    logger.info(" Iniciando servicio Watcher Agent desde main.py")
    watcher = WatcherAgent()
    watcher.run()


def test_ocr() -> None:
    """Prueba del OcrAgent sobre los archivos en data/input/."""

    import json
    from pathlib import Path
    from src.services.ocr_service import OcrService
    from src.agents.ocr_agent import OcrAgent
    from src import config

    output_dir = config.DATA_DIR / "ocr_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Iniciando prueba de OCR Agent")
    ocr_service = OcrService()
    ocr_agent = OcrAgent(ocr_service)
    resultados = ocr_agent.process_directory()

    for r in resultados:
        ocr = r["ocr_resultado"]
        if ocr:
            logger.info(
                "Archivo: {} | Páginas: {} | Palabras: {} | Confianza: {:.2%}",
                r["archivo_nombre"],
                ocr["paginas"],
                ocr["palabras_detectadas"],
                ocr["confianza_promedio"],
            )
            logger.info("Texto (primeros 200 chars): {}", ocr["texto_completo"][:200])

            # Guardar json_export en data/ocr_output/{carpeta}/{archivo}.json
            carpeta_dir = output_dir / r["carpeta_origen"]
            carpeta_dir.mkdir(parents=True, exist_ok=True)
            json_path = carpeta_dir / f"{Path(r['archivo_nombre']).stem}.json"
            json_path.write_text(
                json.dumps(ocr["json_export"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("JSON guardado en: {}", json_path)
        else:
            logger.warning("Archivo: {} | OCR fallido", r["archivo_nombre"])

    logger.info("Prueba finalizada: {} archivos procesados", len(resultados))
    logger.info("JSONs guardados en: {}", output_dir)


if __name__ == "__main__":
    test_ocr()

