"""Modelo Pydantic para la colección 'documentos' en MongoDB."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TipoDocumento = Literal[
    "cedula_identidad",
    "rif",
    "partida_nacimiento",
    "titulo_bachiller",
    "titulo_universitario",
    "titulo_postgrado",
    "certificado_notas_bachillerato",
    "certificado_notas_pregrado",
    "certificado_notas_postgrado",
    "acta_grado",
    "fondo_negro_titulo",
    "nostrificacion",
    "resolucion_nombramiento",
    "evaluacion_docente",
    "diploma_curso",
    "diploma_taller",
    "diploma_congreso",
    "constancia_trabajo",
    "constancia_estudio",
    "carta_recomendacion",
    "curriculo_vitae",
    "otro",
]


class ArchivoInfo(BaseModel):
    """Metadatos del archivo físico almacenado."""

    ruta: str
    nombre_original: str
    formato: str
    tamano_bytes: int | None = None
    hash_sha256: str | None = None


class OcrInfo(BaseModel):
    """Resultado del procesamiento OCR."""

    procesado: bool = False
    fecha_procesamiento: datetime | None = None
    motor: str | None = None
    version_motor: str | None = None
    confianza_promedio: float | None = None
    texto_completo: str | None = None
    idioma_detectado: str | None = None
    paginas: int | None = None
    campos_extraidos: dict[str, Any] = Field(default_factory=dict)


class VerificacionVisual(BaseModel):
    """Preparado para verificación visual futura (no implementado)."""

    procesado: bool = False
    firma: str | None = None
    sello: str | None = None
    fecha_verificacion: datetime | None = None
    motor: str | None = None


class ValidacionDocumento(BaseModel):
    """Estado de validación del documento."""

    estado: Literal[
        "pendiente", "aprobado", "rechazado", "requiere_revision",
    ] = "pendiente"
    es_copia_fiel: bool | None = None
    fecha_emision_documento: datetime | None = None
    fecha_vencimiento: datetime | None = None
    observaciones: str | None = None
    validado_por: str | None = None


class MetadataDocumento(BaseModel):
    """Metadatos operativos del documento."""

    metodo_carga: Literal[
        "escaneo_automatico", "carga_manual", "migracion",
    ] = "escaneo_automatico"
    version_procesamiento: int = 1
    folio: str | None = None
    pagina_expediente: int | None = None


class DocumentoModel(BaseModel):
    """Modelo principal de la colección 'documentos' en MongoDB."""

    docente_id: str
    docente_cedula: str
    tipo: TipoDocumento = "otro"
    nombre: str
    descripcion: str | None = None
    archivo: ArchivoInfo
    ocr: OcrInfo = Field(default_factory=OcrInfo)
    verificacion_visual: VerificacionVisual = Field(default_factory=VerificacionVisual)
    validacion: ValidacionDocumento = Field(default_factory=ValidacionDocumento)
    metadata: MetadataDocumento = Field(default_factory=MetadataDocumento)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
