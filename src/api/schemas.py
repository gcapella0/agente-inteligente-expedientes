from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PaginationMeta(BaseModel):
    total: int
    skip: int
    limit: int
    total_pages: int = 0

    @field_validator("total_pages", mode="before")
    @classmethod
    def compute_pages(cls, v, info):
        total = info.data.get("total", 0)
        limit = info.data.get("limit", 10)
        return (total + limit - 1) // limit if limit > 0 else 0


class ExpedienteResumenResponse(BaseModel):
    numero_expediente: Optional[str] = None
    docente_cedula: str
    docente_nombre: str
    status: str
    completitud_porcentaje: int
    documentos_presentes: list[str] = Field(default_factory=list)
    documentos_faltantes: list[str] = Field(default_factory=list)
    documentos_requeridos_total: int = 0
    ultima_actualizacion: Optional[datetime] = None


class ErrorResponse(BaseModel):
    detail: str
    status_code: int
