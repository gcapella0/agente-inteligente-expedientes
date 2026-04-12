"""Modelo Pydantic para la colección 'docentes' en MongoDB."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ContactoDocente(BaseModel):
    """Datos de contacto del docente."""

    telefono_principal: str | None = None
    telefono_secundario: str | None = None
    email_personal: str | None = None
    email_institucional: str | None = None


class DireccionDocente(BaseModel):
    """Dirección de residencia del docente."""

    estado: str | None = None
    municipio: str | None = None
    direccion_completa: str | None = None
    codigo_postal: str | None = None


class InfoDocente(BaseModel):
    """Información personal del docente."""

    cedula: str
    nombres: str
    apellidos: str
    fecha_nacimiento: date | None = None
    lugar_nacimiento: str | None = None
    nacionalidad: str | None = None
    genero: Literal["M", "F"] | None = None
    estado_civil: Literal[
        "soltero", "casado", "divorciado", "viudo", "union_libre",
    ] | None = None
    contacto: ContactoDocente = Field(default_factory=ContactoDocente)
    direccion: DireccionDocente = Field(default_factory=DireccionDocente)


class FormacionAcademica(BaseModel):
    """Registro de formación académica del docente."""

    nivel: Literal[
        "bachiller", "tecnico", "licenciatura", "especializacion",
        "maestria", "doctorado", "postdoctorado",
    ] | None = None
    titulo_obtenido: str | None = None
    institucion: str | None = None
    pais: str | None = None
    fecha_grado: date | None = None


class VinculacionInstitucional(BaseModel):
    """Datos de vinculación del docente con la institución."""

    fecha_ingreso: date | None = None
    tipo_contratacion: Literal["ordinario", "contratado", "jubilado", "otro"] | None = None
    dedicacion: Literal[
        "exclusiva", "tiempo_completo", "medio_tiempo", "convencional",
    ] | None = None
    categoria: str | None = None
    departamento: str | None = None
    sede: str | None = None
    cargo_actual: str | None = None


class DocumentoRequerido(BaseModel):
    """Indicador de un documento requerido y si está presente."""

    tipo: str
    presente: bool = False


class Completitud(BaseModel):
    """Indicadores de completitud del expediente."""

    porcentaje: int = 0
    documentos_requeridos: list[DocumentoRequerido] = Field(default_factory=list)
    documentos_faltantes: list[str] = Field(default_factory=list)
    documentos_ids: list[str] = Field(default_factory=list)
    ultima_verificacion: datetime | None = None


class DocenteModel(BaseModel):
    """Modelo principal de la colección 'docentes' en MongoDB."""

    expediente_numero: str | None = None
    status: Literal[
        "activo", "inactivo", "en_revision", "completo", "incompleto",
    ] = "incompleto"
    docente: InfoDocente
    formacion_academica: list[FormacionAcademica] = Field(default_factory=list)
    vinculacion_institucional: VinculacionInstitucional = Field(
        default_factory=VinculacionInstitucional,
    )
    completitud: Completitud = Field(default_factory=Completitud)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
