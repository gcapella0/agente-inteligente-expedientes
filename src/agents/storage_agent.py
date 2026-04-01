"""Agente de almacenamiento: persiste documentos clasificados en MongoDB."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime

from src.core.logger import audit_log, get_agent_logger
from src.services.file_service import FileService
from src.services.mongo_service import MongoService

logger = get_agent_logger("storage")


class StorageAgent:
    """Agente que verifica duplicados, persiste en MongoDB y mueve archivos a storage."""

    def __init__(self, mongo_service: MongoService, file_service: FileService) -> None:
        """Inicializa el agente con inyección de dependencias.

        Args:
            mongo_service: Servicio de acceso a MongoDB.
            file_service: Servicio de gestión de archivos.
        """
        self.mongo_service = mongo_service
        self.file_service = file_service

    def process(self, classified_result: dict) -> dict:
        """Procesa un resultado clasificado: persiste en MongoDB y mueve el archivo.

        Flujo:
        1. Verifica que el documento sea válido.
        2. Extrae y normaliza la cédula del docente.
        3. Detecta documentos duplicados por hash SHA-256.
        4. Crea o recupera el registro del docente.
        5. Inserta el documento en MongoDB.
        6. Actualiza la completitud del expediente.
        7. Mueve el archivo a data/storage/{cedula}/.

        Si cualquier paso de MongoDB falla, el archivo NO se mueve
        para permitir el reintento en el próximo ciclo.

        Args:
            classified_result: Dict enriquecido por ClassifierAgent con claves
                archivo_path, archivo_nombre, hash_sha256, ocr_resultado y
                clasificacion.

        Returns:
            Dict con: exito (bool), accion ("insert"|"skip"|"error"),
            docente_id (str|None), documento_id (str|None).
        """
        inicio = time.perf_counter()
        archivo_nombre = classified_result.get("archivo_nombre", "desconocido")
        clasificacion = classified_result.get("clasificacion", {})

        # 1. Verificar que el documento sea válido
        if not clasificacion.get("valido"):
            logger.info("Documento no válido, omitiendo almacenamiento: {}", archivo_nombre)
            audit_log(
                "storage",
                "documento_no_valido",
                "skip",
                archivo=archivo_nombre,
                detalle=json.dumps(
                    {"razon": clasificacion.get("razon_rechazo", "no_valido")}
                ),
            )
            return {"exito": False, "accion": "skip", "docente_id": None, "documento_id": None}

        # 2. Extraer y normalizar cédula
        campos_extraidos = clasificacion.get("campos_extraidos", {})
        cedula_raw = campos_extraidos.get("cedula_titular")
        if not cedula_raw:
            # Fallback: extraer cédula del RIF venezolano (formato V-XXXXXXXX-D)
            numero_rif = campos_extraidos.get("numero_rif", "")
            if numero_rif and numero_rif.upper().lstrip().startswith("V"):
                digitos = re.sub(r"[^\d]", "", numero_rif)
                if len(digitos) > 1:
                    cedula_raw = digitos[:-1]  # El último dígito es el verificador
                    logger.info(
                        "Cédula extraída del RIF {} → {}",
                        numero_rif,
                        cedula_raw,
                    )
        carpeta_origen = classified_result.get("carpeta_origen", "")
        cedula_provisional = False

        if not cedula_raw:
            # Fallback 3: buscar docente existente por nombre de carpeta en MongoDB
            cedula_raw = self._buscar_cedula_por_carpeta(carpeta_origen)
            if cedula_raw:
                logger.info(
                    "Cédula obtenida por carpeta '{}' → {}",
                    carpeta_origen,
                    cedula_raw,
                )

        if not cedula_raw:
            # Fallback 4: usar carpeta como identificador provisional
            if carpeta_origen:
                cedula_raw = carpeta_origen
                cedula_provisional = True
                logger.info(
                    "Sin cédula identificada en {}, usando carpeta '{}' como identificador provisional",
                    archivo_nombre,
                    carpeta_origen,
                )
            else:
                logger.warning("Sin cédula ni carpeta en {}, omitiendo almacenamiento", archivo_nombre)
                audit_log(
                    "storage",
                    "sin_cedula",
                    "error",
                    archivo=archivo_nombre,
                    detalle=json.dumps({"campos_disponibles": list(campos_extraidos.keys())}),
                )
                return {"exito": False, "accion": "error", "docente_id": None, "documento_id": None}

        cedula = cedula_raw if cedula_provisional else self._normalize_cedula(cedula_raw)
        tipo = clasificacion.get("tipo", "otro")

        # 3. Verificar duplicado por hash
        hash_sha256 = classified_result.get("hash_sha256", "")
        try:
            existente = self.mongo_service.find_documento_by_hash(hash_sha256)
        except Exception as exc:
            logger.error("Error consultando duplicado por hash: {}", exc)
            audit_log(
                "storage",
                "almacenamiento_fallido",
                "error",
                cedula=cedula,
                archivo=archivo_nombre,
                detalle=json.dumps({"paso": "find_documento_by_hash", "error": str(exc)}),
            )
            return {"exito": False, "accion": "error", "docente_id": None, "documento_id": None}

        if existente:
            logger.info("Documento duplicado (hash ya existe): {}", archivo_nombre)
            audit_log(
                "storage",
                "documento_duplicado",
                "skip",
                cedula=cedula,
                documento_tipo=tipo,
                archivo=archivo_nombre,
                detalle=json.dumps({"hash_sha256": hash_sha256}),
            )
            return {"exito": False, "accion": "skip", "docente_id": None, "documento_id": None}

        # 4. Obtener o crear docente
        try:
            docente_doc = self.mongo_service.find_docente_by_cedula(cedula)
        except Exception as exc:
            logger.error("Error buscando docente {}: {}", cedula, exc)
            audit_log(
                "storage",
                "almacenamiento_fallido",
                "error",
                cedula=cedula,
                archivo=archivo_nombre,
                detalle=json.dumps({"paso": "find_docente_by_cedula", "error": str(exc)}),
            )
            return {"exito": False, "accion": "error", "docente_id": None, "documento_id": None}

        # Si no se encontró y la cédula es real, verificar si existe un docente provisional
        if docente_doc is None and not cedula_provisional and carpeta_origen:
            try:
                provisional_doc = self.mongo_service.find_docente_by_cedula(carpeta_origen)
                if provisional_doc:
                    self.mongo_service.update_cedula_provisional(carpeta_origen, cedula)
                    docente_id = str(provisional_doc["_id"])
                    docente_doc = provisional_doc
                    logger.info(
                        "Docente provisional '{}' vinculado a cédula real {}",
                        carpeta_origen,
                        cedula,
                    )
            except Exception as exc:
                logger.warning(
                    "Error al vincular docente provisional '{}': {}",
                    carpeta_origen,
                    exc,
                )

        if docente_doc is None:
            try:
                docente_data = self._build_docente_data(
                    cedula,
                    campos_extraidos,
                    classified_result.get("carpeta_origen", ""),
                )
                docente_id = self.mongo_service.insert_docente(docente_data)
                audit_log(
                    "storage",
                    "docente_creado",
                    "ok",
                    cedula=cedula,
                    archivo=archivo_nombre,
                    detalle=json.dumps({"docente_id": docente_id}),
                )
            except Exception as exc:
                logger.error("Error creando docente {}: {}", cedula, exc)
                audit_log(
                    "storage",
                    "almacenamiento_fallido",
                    "error",
                    cedula=cedula,
                    archivo=archivo_nombre,
                    detalle=json.dumps({"paso": "insert_docente", "error": str(exc)}),
                )
                return {"exito": False, "accion": "error", "docente_id": None, "documento_id": None}
        else:
            docente_id = str(docente_doc["_id"])
            logger.info("Docente existente recuperado: cédula={}", cedula)

        # 5. Insertar documento
        try:
            documento_data = self._build_documento_data(classified_result, docente_id, cedula)
            documento_id = self.mongo_service.insert_documento(documento_data)
            audit_log(
                "storage",
                "documento_insertado",
                "ok",
                cedula=cedula,
                documento_tipo=tipo,
                archivo=archivo_nombre,
                detalle=json.dumps({"documento_id": documento_id, "tipo": tipo}),
            )
        except Exception as exc:
            logger.error("Error insertando documento {}: {}", archivo_nombre, exc)
            audit_log(
                "storage",
                "almacenamiento_fallido",
                "error",
                cedula=cedula,
                archivo=archivo_nombre,
                detalle=json.dumps({"paso": "insert_documento", "error": str(exc)}),
            )
            return {"exito": False, "accion": "error", "docente_id": docente_id, "documento_id": None}

        # 6. Actualizar completitud
        try:
            self.mongo_service.update_completitud(cedula)
        except Exception as exc:
            logger.warning("Error actualizando completitud para {}: {}", cedula, exc)

        # 7. Mover archivo a storage
        source_path = classified_result.get("archivo_path")
        archivo_destino = None
        if source_path is not None:
            try:
                fecha_emision = campos_extraidos.get("fecha_emision")
                destino = self.file_service.move_to_storage(
                    source_path, cedula, tipo, fecha_emision
                )
                archivo_destino = str(destino)
                self.mongo_service.update_archivo_ruta(documento_id, archivo_destino)
                audit_log(
                    "storage",
                    "archivo_movido",
                    "ok",
                    cedula=cedula,
                    documento_tipo=tipo,
                    archivo=archivo_nombre,
                    detalle=json.dumps({"destino": archivo_destino}),
                )
            except Exception as exc:
                logger.error(
                    "Error moviendo archivo {} a storage: {}",
                    archivo_nombre,
                    exc,
                )
                audit_log(
                    "storage",
                    "almacenamiento_fallido",
                    "error",
                    cedula=cedula,
                    archivo=archivo_nombre,
                    detalle=json.dumps({"paso": "move_to_storage", "error": str(exc)}),
                )

        tiempo_ms = round((time.perf_counter() - inicio) * 1000, 2)
        logger.info(
            "Almacenamiento completado: {} | cédula={} | tipo={} | {}ms",
            archivo_nombre,
            cedula,
            tipo,
            tiempo_ms,
        )
        return {
            "exito": True,
            "accion": "insert",
            "docente_id": docente_id,
            "documento_id": documento_id,
            "archivo_destino": archivo_destino,
        }

    def _normalize_cedula(self, cedula_raw: str) -> str:
        """Normaliza la cédula eliminando prefijos y dejando solo dígitos.

        Args:
            cedula_raw: Cédula en cualquier formato (V-12345678, V12345678, etc.).

        Returns:
            Cédula normalizada con solo dígitos.
        """
        return re.sub(r"[^\d]", "", cedula_raw)

    def _buscar_cedula_por_carpeta(self, carpeta_origen: str) -> str | None:
        """Busca la cédula de un docente existente usando el nombre de la carpeta.

        Convierte el nombre de carpeta (ej: "Genghis_Capella") en términos de
        búsqueda y consulta MongoDB. Solo retorna cédula si hay exactamente un
        docente que coincida, para evitar asignaciones erróneas.

        Args:
            carpeta_origen: Nombre de la subcarpeta en data/input/.

        Returns:
            Cédula del docente si se encuentra un único match, None si no hay
            coincidencia o hay ambigüedad.
        """
        if not carpeta_origen:
            return None

        palabras = [p for p in re.split(r"[_\s]+", carpeta_origen) if len(p) > 2]
        if not palabras:
            return None

        try:
            condiciones = [
                {
                    "$or": [
                        {"docente.nombres": {"$regex": palabra, "$options": "i"}},
                        {"docente.apellidos": {"$regex": palabra, "$options": "i"}},
                    ]
                }
                for palabra in palabras
            ]
            resultados = list(
                self.mongo_service.docentes.find(
                    {"$and": condiciones},
                    {"docente.cedula": 1},
                )
            )
            if len(resultados) == 1:
                return resultados[0]["docente"]["cedula"]
            if len(resultados) > 1:
                logger.warning(
                    "Búsqueda por carpeta '{}' devolvió {} docentes, se omite para evitar ambigüedad",
                    carpeta_origen,
                    len(resultados),
                )
        except Exception as exc:
            logger.warning("Error buscando docente por carpeta '{}': {}", carpeta_origen, exc)

        return None

    def _build_docente_data(
        self,
        cedula: str,
        campos_extraidos: dict,
        carpeta_origen: str,
    ) -> dict:
        """Construye el dict de datos del docente para insertar en MongoDB.

        Usa los campos extraídos por el LLM y rellena con valores vacíos
        lo que no esté disponible.

        Args:
            cedula: Cédula normalizada del docente.
            campos_extraidos: Campos extraídos por ClassifierAgent.
            carpeta_origen: Nombre de la subcarpeta en data/input/ (ej: "Juan_Perez").

        Returns:
            Dict compatible con DocenteModel.
        """
        nombre_titular = campos_extraidos.get("nombre_titular", "")
        partes = nombre_titular.strip().split() if nombre_titular else []

        if len(partes) >= 2:
            apellidos = partes[-1]
            nombres = " ".join(partes[:-1])
        elif len(partes) == 1:
            nombres = partes[0]
            apellidos = "Pendiente"
        else:
            # Intentar extraer del nombre de la carpeta
            partes_carpeta = carpeta_origen.replace("_", " ").split()
            if len(partes_carpeta) >= 2:
                apellidos = partes_carpeta[-1]
                nombres = " ".join(partes_carpeta[:-1])
            else:
                nombres = carpeta_origen or "Pendiente"
                apellidos = "Pendiente"

        ahora = datetime.now()
        try:
            expediente_numero = self.mongo_service.generate_expediente_numero()
        except Exception:
            expediente_numero = None

        return {
            "expediente_numero": expediente_numero,
            "status": "incompleto",
            "docente": {
                "cedula": cedula,
                "nombres": nombres,
                "apellidos": apellidos,
            },
            "formacion_academica": [],
            "vinculacion_institucional": {},
            "completitud": {
                "porcentaje": 0,
                "documentos_requeridos": [],
                "documentos_faltantes": [],
            },
            "created_at": ahora,
            "updated_at": ahora,
        }

    def _build_documento_data(
        self,
        classified_result: dict,
        docente_id: str,
        cedula: str,
    ) -> dict:
        """Construye el dict de datos del documento para insertar en MongoDB.

        Args:
            classified_result: Resultado completo del pipeline (OCR + clasificación).
            docente_id: ID del docente en MongoDB.
            cedula: Cédula normalizada del docente.

        Returns:
            Dict compatible con DocumentoModel.
        """
        clasificacion = classified_result.get("clasificacion", {})
        ocr = classified_result.get("ocr_resultado") or {}
        campos_extraidos = clasificacion.get("campos_extraidos", {})
        tipo = clasificacion.get("tipo", "otro")
        ahora = datetime.now()

        return {
            "docente_id": docente_id,
            "docente_cedula": cedula,
            "tipo": tipo,
            "nombre": classified_result.get("archivo_nombre", ""),
            "descripcion": None,
            "archivo": {
                "ruta": str(classified_result.get("archivo_path", "")),
                "nombre_original": classified_result.get("archivo_nombre", ""),
                "formato": classified_result.get("formato", ""),
                "tamano_bytes": classified_result.get("tamano_bytes"),
                "hash_sha256": classified_result.get("hash_sha256"),
            },
            "ocr": {
                "procesado": True,
                "fecha_procesamiento": ahora,
                "motor": "doctr",
                "version_motor": "0.9.0",
                "confianza_promedio": ocr.get("confianza_promedio"),
                "texto_completo": ocr.get("texto_completo"),
                "idioma_detectado": ocr.get("idioma_detectado"),
                "paginas": ocr.get("paginas"),
                "campos_extraidos": campos_extraidos,
            },
            "verificacion_visual": {
                "procesado": False,
                "firma": None,
                "sello": None,
            },
            "validacion": {
                "estado": "pendiente",
            },
            "metadata": {
                "metodo_carga": "escaneo_automatico",
                "version_procesamiento": 1,
            },
            "created_at": ahora,
            "updated_at": ahora,
        }
