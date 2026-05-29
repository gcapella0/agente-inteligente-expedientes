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


def test_ocr(usar_cache: bool = False) -> None:
    """Prueba del OcrAgent sobre los archivos en data/input/."""

    import json
    from pathlib import Path
    from src.services.ocr_service import OcrService
    from src.agents.ocr_agent import OcrAgent
    from src import config

    output_dir = config.DATA_DIR / "ocr_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    state_file = config.DATA_DIR / "processed_pipeline.json"
    if usar_cache:
        hashes_procesados = _load_processed_hashes(state_file)
        logger.info("OCR: {} archivos ya procesados (se omitirán)", len(hashes_procesados))
    else:
        hashes_procesados = set()
        logger.info("OCR: modo independiente, procesando todos los archivos")

    logger.info("Iniciando prueba de OCR Agent")
    ocr_service = OcrService()
    ocr_agent = OcrAgent(ocr_service)
    resultados = ocr_agent.process_directory(skip_hashes=hashes_procesados)

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
            hashes_procesados.add(r["hash_sha256"])
        else:
            logger.warning("Archivo: {} | OCR fallido", r["archivo_nombre"])

    if usar_cache:
        _save_processed_hashes(state_file, hashes_procesados)
    logger.info("Prueba finalizada: {} archivos procesados", len(resultados))
    logger.info("JSONs guardados en: {}", output_dir)


def test_classifier(usar_cache: bool = False) -> None:
    """Prueba del pipeline OCR + Clasificador sobre data/input/."""

    import json
    from pathlib import Path
    from src.services.ocr_service import OcrService
    from src.agents.ocr_agent import OcrAgent
    from src.services.llm_service import LlmService
    from src.services.llm import create_llm_provider
    from src.agents.classifier_agent import ClassifierAgent
    from src import config

    output_dir = config.DATA_DIR / "classifier_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    state_file = config.DATA_DIR / "processed_pipeline.json"
    if usar_cache:
        hashes_procesados = _load_processed_hashes(state_file)
        logger.info("Classifier: {} archivos ya procesados (se omitirán)", len(hashes_procesados))
    else:
        hashes_procesados = set()
        logger.info("Classifier: modo independiente, procesando todos los archivos")

    # 1. OCR
    logger.info("=== Paso 1: OCR ===")
    ocr_service = OcrService()
    ocr_agent = OcrAgent(ocr_service)
    resultados_ocr = ocr_agent.process_directory(skip_hashes=hashes_procesados)

    if not resultados_ocr:
        logger.info("No hay archivos nuevos para clasificar.")
        return

    # 2. Clasificación
    logger.info("=== Paso 2: Clasificación ===")
    llm_service = LlmService(create_llm_provider())
    classifier = ClassifierAgent(llm_service)

    resultados_clasificados = []
    for ocr_result in resultados_ocr:
        resultado = classifier.classify(ocr_result)
        resultados_clasificados.append(resultado)
        if usar_cache:
            hashes_procesados.add(resultado["hash_sha256"])
            _save_processed_hashes(state_file, hashes_procesados)

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


def test_storage(usar_cache: bool = False) -> None:
    """Prueba del pipeline OCR → Clasificador → StorageAgent sobre data/input/."""

    from src.services.ocr_service import OcrService
    from src.agents.ocr_agent import OcrAgent
    from src.services.llm_service import LlmService
    from src.services.llm import create_llm_provider
    from src.agents.classifier_agent import ClassifierAgent
    from src.services.mongo_service import MongoService
    from src.services.file_service import FileService
    from src.agents.storage_agent import StorageAgent
    from src import config

    config.validate_ocr()
    config.ensure_directories()

    state_file = config.DATA_DIR / "processed_pipeline.json"
    if usar_cache:
        hashes_procesados = _load_processed_hashes(state_file)
        logger.info("Storage: {} archivos ya procesados (se omitirán)", len(hashes_procesados))
    else:
        hashes_procesados = set()
        logger.info("Storage: modo independiente, procesando todos los archivos")

    # 1. OCR
    logger.info("=== Paso 1: OCR ===")
    ocr_service = OcrService()
    ocr_agent = OcrAgent(ocr_service)
    resultados_ocr = ocr_agent.process_directory(skip_hashes=hashes_procesados)

    if not resultados_ocr:
        logger.info("No hay archivos nuevos para procesar en data/input/")
        return

    # 2. Clasificación
    logger.info("=== Paso 2: Clasificación ===")
    llm_service = LlmService(create_llm_provider())
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
            if usar_cache:
                hashes_procesados.add(resultado["hash_sha256"])
                _save_processed_hashes(state_file, hashes_procesados)
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
    from src.services.llm import create_llm_provider
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
    llm_service = LlmService(create_llm_provider())
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


def enriquecer_expedientes_desde_cv() -> None:
    """Enriquece los expedientes en MongoDB con datos de los CVs ya almacenados.

    Consulta todos los documentos de tipo curriculo_vitae en la colección
    documentos y llama a enriquecer_docente_desde_cv para cada uno.
    Solo sobreescribe campos que estén vacíos en el perfil del docente.

    Uso: ejecutar una única vez tras agregar lógica de enriquecimiento nueva.
    """
    from src.services.mongo_service import MongoService
    from src import config

    config.validate_ocr()

    mongo = MongoService()
    cursor = mongo.documentos.find(
        {"tipo": "curriculo_vitae"},
        {"docente_cedula": 1, "ocr.campos_extraidos": 1},
    )

    total = 0
    errores = 0
    for doc in cursor:
        cedula = doc.get("docente_cedula", "")
        campos = doc.get("ocr", {}).get("campos_extraidos", {})
        if not cedula or not campos:
            logger.warning(
                "CV sin cédula o sin campos extraídos (_id={}), omitido",
                doc.get("_id"),
            )
            continue
        try:
            mongo.enriquecer_docente_desde_cv(cedula, campos)
            logger.info("Expediente enriquecido: cédula={}", cedula)
            total += 1
        except Exception as exc:
            logger.error("Error enriqueciendo cédula={}: {}", cedula, exc)
            errores += 1

    logger.info(
        "Enriquecimiento completado: {} expedientes actualizados, {} errores",
        total,
        errores,
    )


def test_compression() -> None:
    """Prueba de compresión sobre los archivos en data/input/.

    Comprime cada PDF e imagen encontrada, muestra tamaño original,
    tamaño comprimido y ratio de reducción. No mueve ni elimina ningún
    archivo original; los temporales se limpian al finalizar.
    """
    from pathlib import Path
    from src.agents.storage_agent import StorageAgent
    from src.services.file_service import FileService
    from src.services.mongo_service import MongoService
    from src import config

    config.ensure_directories()

    EXTENSIONES = {".pdf", ".jpg", ".jpeg", ".png"}
    archivos: list[Path] = []
    for carpeta in config.INPUT_DIR.iterdir():
        if carpeta.is_dir():
            archivos.extend(
                f for f in carpeta.iterdir() if f.suffix.lower() in EXTENSIONES
            )
    if not archivos:
        for f in config.INPUT_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in EXTENSIONES:
                archivos.append(f)

    if not archivos:
        logger.warning(
            "No se encontraron archivos PDF/imagen en {}", config.INPUT_DIR
        )
        return

    logger.info("=== Prueba de compresión: {} archivo(s) ===", len(archivos))

    # Instanciar StorageAgent solo para acceder a los métodos de compresión
    agent = StorageAgent.__new__(StorageAgent)

    total_original = 0
    total_comprimido = 0
    comprimidos = 0
    sin_reduccion = 0
    errores = 0

    for archivo in sorted(archivos):
        tamano_orig = archivo.stat().st_size
        total_original += tamano_orig
        ext = archivo.suffix.lower()
        cedula_temp = "test_compresion"

        temp_result: Path | None = None
        if ext == ".pdf":
            temp_result = agent._compress_pdf(archivo, cedula_temp)
        elif ext in (".jpg", ".jpeg", ".png"):
            temp_result = agent._compress_image(archivo, cedula_temp)

        if temp_result is None:
            logger.warning("  FALLO | {} | compresión no disponible", archivo.name)
            total_comprimido += tamano_orig
            errores += 1
            continue

        tamano_comp = temp_result.stat().st_size
        if tamano_comp < tamano_orig:
            ratio = tamano_comp / tamano_orig
            logger.info(
                "  OK    | {} | {} → {} bytes ({:.0%})",
                archivo.name,
                tamano_orig,
                tamano_comp,
                ratio,
            )
            total_comprimido += tamano_comp
            comprimidos += 1
        else:
            logger.info(
                "  IGUAL | {} | {} bytes (no se redujo, se usa original)",
                archivo.name,
                tamano_orig,
            )
            total_comprimido += tamano_orig
            sin_reduccion += 1

        # Limpiar archivo temporal
        try:
            temp_result.unlink(missing_ok=True)
        except OSError:
            pass

    # Limpiar directorio temporal
    temp_dir = config.STORAGE_DIR / cedula_temp / "temp"
    try:
        if temp_dir.exists():
            temp_dir.rmdir()
        parent = temp_dir.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass

    if total_original > 0:
        ratio_global = total_comprimido / total_original
        ahorro = total_original - total_comprimido
        logger.info(
            "=== Resumen: {} OK | {} sin reducción | {} fallos ===",
            comprimidos,
            sin_reduccion,
            errores,
        )
        logger.info(
            "Total: {} → {} bytes | ahorro: {} bytes ({:.0%})",
            total_original,
            total_comprimido,
            ahorro,
            ratio_global,
        )


if __name__ == "__main__":
    test_compression()

