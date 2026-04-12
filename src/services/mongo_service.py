"""Servicio de acceso a MongoDB para la colección de expedientes docentes."""

from __future__ import annotations

from datetime import datetime

from pymongo import ASCENDING, DESCENDING, TEXT, MongoClient
from pymongo.errors import PyMongoError

from src import config
from src.core.logger import get_agent_logger
from src.models.docente import DocenteModel
from src.models.documento import DocumentoModel

logger = get_agent_logger("storage")

_DOCUMENTOS_REQUERIDOS = [
    "cedula_identidad",
    "partida_nacimiento",
    "rif",
    "titulo_bachiller",
    "certificado_notas_bachillerato",
    "titulo_universitario",
    "certificado_notas_pregrado",
    "fondo_negro_titulo",
    "acta_grado",
    "resolucion_nombramiento",
]


class MongoService:
    """Servicio de persistencia en MongoDB para docentes y documentos."""

    def __init__(self) -> None:
        """Inicializa la conexión a MongoDB y configura los índices."""
        self.client = MongoClient(config.MONGO_URI)
        self.db = self.client[config.MONGO_DB]
        self.docentes = self.db["docentes"]
        self.documentos = self.db["documentos"]
        self.setup_indexes()
        logger.info("MongoService inicializado: {}", config.MONGO_URI)

    def setup_indexes(self) -> None:
        """Crea los índices necesarios en las colecciones de MongoDB."""
        try:
            # Índices de la colección docentes
            self.docentes.create_index(
                "expediente_numero", unique=True, sparse=True, background=True,
            )
            self.docentes.create_index(
                "docente.cedula", unique=True, background=True,
            )
            self.docentes.create_index(
                [("docente.apellidos", ASCENDING), ("docente.nombres", ASCENDING)],
                background=True,
            )
            self.docentes.create_index(
                "vinculacion_institucional.departamento", background=True,
            )
            self.docentes.create_index(
                "vinculacion_institucional.sede", background=True,
            )
            self.docentes.create_index("status", background=True)
            self.docentes.create_index("completitud.porcentaje", background=True)

            # Índices de la colección documentos
            self.documentos.create_index("docente_id", background=True)
            self.documentos.create_index("docente_cedula", background=True)
            self.documentos.create_index("tipo", background=True)
            self.documentos.create_index("validacion.estado", background=True)
            self.documentos.create_index("ocr.procesado", background=True)
            self.documentos.create_index(
                [("docente_cedula", ASCENDING), ("tipo", ASCENDING)],
                background=True,
            )
            self.documentos.create_index(
                [("created_at", DESCENDING)], background=True,
            )
            self.documentos.create_index(
                [("ocr.texto_completo", TEXT)], background=True,
            )

            logger.info("Índices de MongoDB configurados correctamente")
        except PyMongoError as exc:
            logger.warning("Error al configurar índices de MongoDB: {}", exc)

    def find_docente_by_cedula(self, cedula: str) -> dict | None:
        """Busca un docente por su número de cédula.

        Args:
            cedula: Número de cédula sin prefijo (solo dígitos).

        Returns:
            Documento de MongoDB o None si no existe.
        """
        try:
            return self.docentes.find_one({"docente.cedula": cedula})
        except PyMongoError as exc:
            logger.error("Error al buscar docente con cédula {}: {}", cedula, exc)
            raise

    def find_documento_by_hash(self, hash_sha256: str) -> dict | None:
        """Busca un documento por su hash SHA-256.

        Args:
            hash_sha256: Hash SHA-256 del archivo.

        Returns:
            Documento de MongoDB o None si no existe.
        """
        try:
            return self.documentos.find_one({"archivo.hash_sha256": hash_sha256})
        except PyMongoError as exc:
            logger.error(
                "Error al buscar documento por hash {}: {}", hash_sha256, exc,
            )
            raise

    def insert_docente(self, docente_data: dict) -> str:
        """Valida e inserta un nuevo docente en MongoDB.

        Args:
            docente_data: Diccionario con los datos del docente.

        Returns:
            ID del documento insertado como string.

        Raises:
            ValueError: Si los datos no son válidos según el modelo Pydantic.
            PyMongoError: Si falla la inserción en MongoDB.
        """
        validado = DocenteModel(**docente_data).model_dump()
        try:
            resultado = self.docentes.insert_one(validado)
            docente_id = str(resultado.inserted_id)
            logger.info("Docente insertado: _id={}", docente_id)
            return docente_id
        except PyMongoError as exc:
            logger.error("Error al insertar docente: {}", exc)
            raise

    def insert_documento(self, documento_data: dict) -> str:
        """Valida e inserta un nuevo documento en MongoDB.

        Args:
            documento_data: Diccionario con los datos del documento.

        Returns:
            ID del documento insertado como string.

        Raises:
            ValueError: Si los datos no son válidos según el modelo Pydantic.
            PyMongoError: Si falla la inserción en MongoDB.
        """
        validado = DocumentoModel(**documento_data).model_dump()
        try:
            resultado = self.documentos.insert_one(validado)
            documento_id = str(resultado.inserted_id)
            logger.info("Documento insertado: _id={}", documento_id)
            return documento_id
        except PyMongoError as exc:
            logger.error("Error al insertar documento: {}", exc)
            raise

    def update_completitud(self, cedula: str) -> None:
        """Recalcula y actualiza el porcentaje de completitud del expediente.

        Consulta los tipos de documentos presentes del docente y actualiza
        el campo completitud en la colección docentes.

        Args:
            cedula: Número de cédula del docente (sin prefijo).
        """
        try:
            docs = list(self.documentos.find(
                {"docente_cedula": cedula, "validacion.estado": {"$ne": "rechazado"}},
                {"_id": 1, "tipo": 1},
            ))
            tipos_presentes = {d["tipo"] for d in docs}
            documentos_ids = [str(d["_id"]) for d in docs]

            documentos_requeridos = []
            faltantes = []
            for tipo in _DOCUMENTOS_REQUERIDOS:
                presente = tipo in tipos_presentes
                documentos_requeridos.append({"tipo": tipo, "presente": presente})
                if not presente:
                    faltantes.append(tipo)

            total = len(_DOCUMENTOS_REQUERIDOS)
            presentes = total - len(faltantes)
            porcentaje = round(presentes / total * 100)

            self.docentes.update_one(
                {"docente.cedula": cedula},
                {
                    "$set": {
                        "completitud.porcentaje": porcentaje,
                        "completitud.documentos_requeridos": documentos_requeridos,
                        "completitud.documentos_faltantes": faltantes,
                        "completitud.documentos_ids": documentos_ids,
                        "completitud.ultima_verificacion": datetime.now(),
                        "updated_at": datetime.now(),
                    }
                },
            )
            logger.info(
                "Completitud actualizada para cédula {}: {}%",
                cedula,
                porcentaje,
            )
        except PyMongoError as exc:
            logger.error(
                "Error al actualizar completitud para cédula {}: {}",
                cedula,
                exc,
            )
            raise

    def generate_expediente_numero(self) -> str:
        """Genera un número de expediente secuencial único.

        Formato: EXP-{año}-{secuencia:06d}

        Returns:
            Número de expediente como string, ej: "EXP-2026-000001".
        """
        try:
            año = datetime.now().year
            prefijo = f"EXP-{año}-"
            count = self.docentes.count_documents(
                {"expediente_numero": {"$regex": f"^{prefijo}"}}
            )
            return f"{prefijo}{count + 1:06d}"
        except PyMongoError as exc:
            logger.error("Error al generar número de expediente: {}", exc)
            raise

    def update_cedula_provisional(self, cedula_provisional: str, cedula_real: str) -> None:
        """Reemplaza la cédula provisional de un docente por su cédula real.

        Actualiza el registro del docente y todos sus documentos asociados.

        Args:
            cedula_provisional: Identificador provisional (ej: nombre de carpeta).
            cedula_real: Cédula real del docente (solo dígitos).
        """
        try:
            ahora = datetime.now()
            self.docentes.update_one(
                {"docente.cedula": cedula_provisional},
                {"$set": {"docente.cedula": cedula_real, "updated_at": ahora}},
            )
            self.documentos.update_many(
                {"docente_cedula": cedula_provisional},
                {"$set": {"docente_cedula": cedula_real, "updated_at": ahora}},
            )
            logger.info(
                "Cédula provisional '{}' actualizada a cédula real '{}'",
                cedula_provisional,
                cedula_real,
            )
        except PyMongoError as exc:
            logger.error(
                "Error actualizando cédula provisional '{}' a '{}': {}",
                cedula_provisional,
                cedula_real,
                exc,
            )
            raise

    def enriquecer_docente_desde_cv(self, cedula: str, campos: dict) -> None:
        """Actualiza el perfil del docente con datos extraídos de su currículo vitae.

        Solo sobreescribe campos que estén vacíos (None) en el registro actual.
        La formación académica se añade como nueva entrada si hay título.

        Args:
            cedula: Cédula normalizada del docente.
            campos: Campos extraídos por el LLM del CV (correo_electronico,
                telefono, titulo_academico, institucion_emisora, etc.).
        """
        try:
            set_data: dict = {}
            if campos.get("correo_electronico"):
                set_data["docente.contacto.email_personal"] = campos["correo_electronico"]
            if campos.get("telefono"):
                set_data["docente.contacto.telefono_principal"] = campos["telefono"]

            if set_data:
                set_data["updated_at"] = datetime.now()
                # $set solo en campos que actualmente sean None
                condiciones_nulos = {k: None for k in set_data if k != "updated_at"}
                self.docentes.update_one(
                    {"docente.cedula": cedula, **condiciones_nulos},
                    {"$set": set_data},
                )

            if campos.get("titulo_academico"):
                formacion = {
                    "titulo_obtenido": campos.get("titulo_academico"),
                    "institucion": campos.get("institucion_emisora"),
                }
                self.docentes.update_one(
                    {"docente.cedula": cedula},
                    {"$addToSet": {"formacion_academica": formacion}},
                )

            logger.info("Perfil del docente {} enriquecido con datos del CV", cedula)
        except PyMongoError as exc:
            logger.warning(
                "Error enriqueciendo perfil del docente {} desde CV: {}", cedula, exc,
            )
            raise

    def update_archivo_ruta(self, documento_id: str, ruta: str) -> None:
        """Actualiza la ruta del archivo en un documento ya insertado.

        Args:
            documento_id: ID del documento en MongoDB (string).
            ruta: Nueva ruta del archivo.
        """
        from bson import ObjectId

        try:
            self.documentos.update_one(
                {"_id": ObjectId(documento_id)},
                {
                    "$set": {
                        "archivo.ruta": ruta,
                        "updated_at": datetime.now(),
                    }
                },
            )
            logger.debug("Ruta de archivo actualizada: _id={}", documento_id)
        except PyMongoError as exc:
            logger.error(
                "Error al actualizar ruta del documento {}: {}",
                documento_id,
                exc,
            )
            raise
