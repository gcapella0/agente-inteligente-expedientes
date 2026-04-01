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


def test_watcher() -> None:
    """Prueba del WatcherAgent: ejecuta un ciclo IMAP y descarga adjuntos."""

    from src import config

    config.validate()
    config.ensure_directories()

    logger.info("=== Prueba: WatcherAgent ===")
    watcher = WatcherAgent()
    if watcher._connect_imap():
        nuevos = watcher._check_new_emails()
        watcher._disconnect_imap()
        logger.info("Watcher: {} correo(s) procesado(s)", nuevos)
    else:
        logger.warning("No se pudo conectar a IMAP")


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

            # Guardar json_ligero en data/ocr_output/{carpeta}/{archivo}.json
            carpeta_dir = output_dir / r["carpeta_origen"]
            carpeta_dir.mkdir(parents=True, exist_ok=True)
            json_path = carpeta_dir / f"{Path(r['archivo_nombre']).stem}.json"
            json_path.write_text(
                json.dumps(ocr["json_ligero"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("JSON guardado en: {}", json_path)
        else:
            logger.warning("Archivo: {} | OCR fallido", r["archivo_nombre"])

    logger.info("Prueba finalizada: {} archivos procesados", len(resultados))
    logger.info("JSONs guardados en: {}", output_dir)


def test_classifier() -> None:
    """Prueba del pipeline OCR + Clasificador sobre data/input/."""

    import json
    from pathlib import Path
    from src.services.ocr_service import OcrService
    from src.agents.ocr_agent import OcrAgent
    from src.services.llm_service import LlmService
    from src.agents.classifier_agent import ClassifierAgent
    from src import config

    output_dir = config.DATA_DIR / "classifier_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. OCR
    logger.info("=== Paso 1: OCR ===")
    ocr_service = OcrService()
    ocr_agent = OcrAgent(ocr_service)
    resultados_ocr = ocr_agent.process_directory()

    if not resultados_ocr:
        logger.warning("No hay archivos para procesar en data/input/")
        return

    # 2. Clasificación
    logger.info("=== Paso 2: Clasificación ===")
    llm_service = LlmService()
    classifier = ClassifierAgent(llm_service)

    resultados_clasificados = []
    for ocr_result in resultados_ocr:
        resultado = classifier.classify(ocr_result)
        resultados_clasificados.append(resultado)

    # 3. Mostrar resultados y guardar
    for r in resultados_clasificados:
        c = r.get("clasificacion", {})
        if c.get("valido"):
            logger.info(
                "VÁLIDO  | {} | tipo: {} | confianza: {:.2%} | campos: {}",
                r["archivo_nombre"],
                c["tipo"],
                c["confianza_clasificacion"],
                list(c["campos_extraidos"].keys()),
            )
        else:
            logger.info(
                "RECHAZADO | {} | razón: {}",
                r["archivo_nombre"],
                c.get("razon_rechazo", "sin razón"),
            )

        # Guardar resultado completo en JSON
        carpeta_dir = output_dir / r["carpeta_origen"]
        carpeta_dir.mkdir(parents=True, exist_ok=True)
        json_path = carpeta_dir / f"{Path(r['archivo_nombre']).stem}_clasificado.json"

        salida = {
            "archivo_nombre": r["archivo_nombre"],
            "carpeta_origen": r["carpeta_origen"],
            "formato": r["formato"],
            "tamano_bytes": r["tamano_bytes"],
            "hash_sha256": r["hash_sha256"],
            "clasificacion": c,
        }
        json_path.write_text(
            json.dumps(salida, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    logger.info(
        "Pipeline finalizado: {} archivos clasificados. Resultados en: {}",
        len(resultados_clasificados),
        output_dir,
    )


def test_storage() -> None:
    """Prueba del pipeline OCR → Clasificador → StorageAgent sobre data/input/."""

    from src.services.ocr_service import OcrService
    from src.agents.ocr_agent import OcrAgent
    from src.services.llm_service import LlmService
    from src.agents.classifier_agent import ClassifierAgent
    from src.services.mongo_service import MongoService
    from src.services.file_service import FileService
    from src.agents.storage_agent import StorageAgent
    from src import config

    config.validate_ocr()
    config.ensure_directories()

    # 1. OCR
    logger.info("=== Paso 1: OCR ===")
    ocr_service = OcrService()
    ocr_agent = OcrAgent(ocr_service)
    resultados_ocr = ocr_agent.process_directory()

    if not resultados_ocr:
        logger.warning("No hay archivos para procesar en data/input/")
        return

    # 2. Clasificación
    logger.info("=== Paso 2: Clasificación ===")
    llm_service = LlmService()
    classifier = ClassifierAgent(llm_service)
    resultados_clasificados = [classifier.classify(r) for r in resultados_ocr]

    # 3. Almacenamiento
    logger.info("=== Paso 3: Almacenamiento ===")
    mongo_service = MongoService()
    file_service = FileService()
    storage_agent = StorageAgent(mongo_service, file_service)

    almacenados = 0
    omitidos = 0
    errores = 0
    for resultado in resultados_clasificados:
        storage_result = storage_agent.process(resultado)
        if storage_result.get("exito"):
            almacenados += 1
        elif storage_result.get("accion") == "skip":
            omitidos += 1
        else:
            errores += 1

    logger.info(
        "StorageAgent: {} almacenados, {} omitidos, {} errores",
        almacenados,
        omitidos,
        errores,
    )


def _load_processed_hashes(state_file: "Path") -> set[str]:
    """Carga hashes de archivos ya procesados por el pipeline."""
    if not state_file.exists():
        return set()
    try:
        import json
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return set(data.get("hashes", []))
    except (json.JSONDecodeError, ValueError):
        logger.warning("Archivo de estado del pipeline corrupto, se reiniciará")
        return set()


def _save_processed_hashes(state_file: "Path", hashes: set[str]) -> None:
    """Guarda hashes de archivos procesados por el pipeline."""
    import json
    state_file.write_text(
        json.dumps({"hashes": sorted(hashes)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_pipeline() -> None:
    """Pipeline completo: Watcher (1 ciclo) → OCR → Clasificador → Almacenamiento.

    Archivos ya clasificados (por hash SHA-256) se omiten automáticamente
    para evitar gastar tokens del LLM innecesariamente.
    """

    import json
    from pathlib import Path
    from src.services.ocr_service import OcrService
    from src.agents.ocr_agent import OcrAgent
    from src.services.llm_service import LlmService
    from src.agents.classifier_agent import ClassifierAgent
    from src import config

    config.validate()
    config.ensure_directories()

    state_file = config.DATA_DIR / "processed_pipeline.json"
    hashes_procesados = _load_processed_hashes(state_file)
    logger.info("Estado del pipeline: {} archivos ya procesados", len(hashes_procesados))

    # 1. Watcher — un solo ciclo de descarga
    logger.info("=== Paso 1: Watcher (un ciclo) ===")
    watcher = WatcherAgent()
    if watcher._connect_imap():
        nuevos = watcher._check_new_emails()
        watcher._disconnect_imap()
        logger.info("Watcher: {} correo(s) procesado(s)", nuevos)
    else:
        logger.warning("No se pudo conectar a IMAP, continuando con archivos existentes")

    # 2. OCR (salta archivos ya clasificados por hash)
    logger.info("=== Paso 2: OCR ===")
    ocr_service = OcrService()
    ocr_agent = OcrAgent(ocr_service)
    resultados_ocr = ocr_agent.process_directory(skip_hashes=hashes_procesados)

    if not resultados_ocr:
        logger.info("No hay archivos nuevos para procesar.")
        return

    logger.info("OCR: {} archivos nuevos para clasificar", len(resultados_ocr))

    # 3. Clasificación
    logger.info("=== Paso 3: Clasificación ===")
    llm_service = LlmService()
    classifier = ClassifierAgent(llm_service)

    output_dir = config.DATA_DIR / "classifier_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    resultados_clasificados = []
    for ocr_result in resultados_ocr:
        resultado = classifier.classify(ocr_result)
        resultados_clasificados.append(resultado)

        # Registrar hash inmediatamente tras clasificar
        hashes_procesados.add(resultado["hash_sha256"])
        _save_processed_hashes(state_file, hashes_procesados)

    # 4. Resultados
    logger.info("=== Resultados ===")
    validos = 0
    for r in resultados_clasificados:
        c = r.get("clasificacion", {})
        if c.get("valido"):
            validos += 1
            logger.info(
                "VÁLIDO  | {} | tipo: {} | confianza: {:.2%} | campos: {}",
                r["archivo_nombre"],
                c["tipo"],
                c["confianza_clasificacion"],
                list(c["campos_extraidos"].keys()),
            )
        else:
            logger.info(
                "RECHAZADO | {} | razón: {}",
                r["archivo_nombre"],
                c.get("razon_rechazo", "sin razón"),
            )

        carpeta_dir = output_dir / r["carpeta_origen"]
        carpeta_dir.mkdir(parents=True, exist_ok=True)
        json_path = carpeta_dir / f"{Path(r['archivo_nombre']).stem}_clasificado.json"

        salida = {
            "archivo_nombre": r["archivo_nombre"],
            "carpeta_origen": r["carpeta_origen"],
            "formato": r["formato"],
            "tamano_bytes": r["tamano_bytes"],
            "hash_sha256": r["hash_sha256"],
            "clasificacion": c,
        }
        json_path.write_text(
            json.dumps(salida, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    logger.info(
        "Clasificación: {}/{} válidos. Resultados en: {}",
        validos,
        len(resultados_clasificados),
        output_dir,
    )

    # 4. Almacenamiento
    logger.info("=== Paso 4: Almacenamiento ===")
    from src.services.mongo_service import MongoService
    from src.services.file_service import FileService
    from src.agents.storage_agent import StorageAgent

    mongo_service = MongoService()
    file_service = FileService()
    storage_agent = StorageAgent(mongo_service, file_service)

    almacenados = 0
    errores_storage = 0
    for resultado in resultados_clasificados:
        storage_result = storage_agent.process(resultado)
        if storage_result.get("exito"):
            almacenados += 1
        elif storage_result.get("accion") != "skip":
            errores_storage += 1

    logger.info(
        "Pipeline completo: {} almacenados, {} omitidos, {} errores",
        almacenados,
        len(resultados_clasificados) - almacenados - errores_storage,
        errores_storage,
    )


if __name__ == "__main__":
    test_pipeline()

