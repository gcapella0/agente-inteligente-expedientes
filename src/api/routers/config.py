from __future__ import annotations

from fastapi import APIRouter

from src.core.logger import get_agent_logger

router = APIRouter()
logger = get_agent_logger("api")

_TIPOS_DOCUMENTO = [
    {"id": "cedula_identidad", "nombre": "Cédula de Identidad", "obligatorio": True, "descripcion": "Documento de identificación personal", "formatos_aceptados": ["pdf", "jpg", "png"], "tamaño_maximo_mb": 25},
    {"id": "rif", "nombre": "RIF", "obligatorio": True, "descripcion": "Registro de Identificación Fiscal", "formatos_aceptados": ["pdf", "jpg", "png"], "tamaño_maximo_mb": 25},
    {"id": "partida_nacimiento", "nombre": "Partida de Nacimiento", "obligatorio": True, "descripcion": "Acta de nacimiento", "formatos_aceptados": ["pdf", "jpg", "png"], "tamaño_maximo_mb": 25},
    {"id": "titulo_bachiller", "nombre": "Título de Bachiller", "obligatorio": True, "descripcion": "Diploma de educación media", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "certificado_notas_bachillerato", "nombre": "Certificado de Notas (Bachillerato)", "obligatorio": True, "descripcion": "Historial académico de secundaria", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "titulo_universitario", "nombre": "Título Universitario", "obligatorio": True, "descripcion": "Diploma de licenciatura o grado", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "certificado_notas_pregrado", "nombre": "Certificado de Notas (Pregrado)", "obligatorio": True, "descripcion": "Historial académico universitario", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "fondo_negro_titulo", "nombre": "Fondo Negro del Título", "obligatorio": True, "descripcion": "Copia de seguridad del título", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "acta_grado", "nombre": "Acta de Grado", "obligatorio": True, "descripcion": "Registro oficial de graduación", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "resolucion_nombramiento", "nombre": "Resolución de Nombramiento", "obligatorio": True, "descripcion": "Documento de asignación como docente", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "certificado_notas_postgrado", "nombre": "Certificado de Notas (Postgrado)", "obligatorio": False, "descripcion": "Historial académico de especialización/maestría", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "titulo_postgrado", "nombre": "Título de Postgrado", "obligatorio": False, "descripcion": "Diploma de especialización, maestría o doctorado", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "diploma_curso", "nombre": "Diploma de Curso", "obligatorio": False, "descripcion": "Certificado de curso completado", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "diploma_taller", "nombre": "Diploma de Taller", "obligatorio": False, "descripcion": "Certificado de taller asistido", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "diploma_congreso", "nombre": "Diploma de Congreso", "obligatorio": False, "descripcion": "Certificado de participación en congreso", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "constancia_trabajo", "nombre": "Constancia de Trabajo", "obligatorio": False, "descripcion": "Comprobante de experiencia laboral", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "constancia_estudio", "nombre": "Constancia de Estudio", "obligatorio": False, "descripcion": "Comprobante de matrícula o estudio actual", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "carta_recomendacion", "nombre": "Carta de Recomendación", "obligatorio": False, "descripcion": "Referencia de profesionales", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "curriculo_vitae", "nombre": "Currículum Vitae", "obligatorio": False, "descripcion": "Resumen de carrera profesional", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "nostrificacion", "nombre": "Nostrificación", "obligatorio": False, "descripcion": "Reconocimiento de título extranjero", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "evaluacion_docente", "nombre": "Evaluación Docente", "obligatorio": False, "descripcion": "Resultado de evaluación de desempeño", "formatos_aceptados": ["pdf"], "tamaño_maximo_mb": 25},
    {"id": "otro", "nombre": "Otro", "obligatorio": False, "descripcion": "Documento no clasificado", "formatos_aceptados": ["pdf", "jpg", "png"], "tamaño_maximo_mb": 25},
]

_DOCUMENTOS_REQUERIDOS = sum(1 for t in _TIPOS_DOCUMENTO if t["obligatorio"])


@router.get("/tipos-documento")
async def obtener_tipos_documento():
    """Lista de tipos de documentos posibles."""
    logger.info("Tipos de documento listados")
    return {
        "tipos_documento": _TIPOS_DOCUMENTO,
        "documentos_requeridos": _DOCUMENTOS_REQUERIDOS,
        "total_tipos_posibles": len(_TIPOS_DOCUMENTO),
    }


@router.get("/estados-validacion")
async def obtener_estados_validacion():
    """Estados posibles de validación de un documento."""
    logger.info("Estados de validación listados")
    return {
        "estados": [
            {"id": "pendiente", "descripcion": "Esperando revisión"},
            {"id": "aprobado", "descripcion": "Válido para expediente"},
            {"id": "rechazado", "descripcion": "No cumple requisitos"},
            {"id": "requiere_revision", "descripcion": "Requiere aclaración"},
        ]
    }


@router.get("/estados-docente")
async def obtener_estados_docente():
    """Estados posibles de un docente."""
    logger.info("Estados de docente listados")
    return {
        "estados": [
            {"id": "activo", "descripcion": "Docente activo"},
            {"id": "inactivo", "descripcion": "Docente inactivo"},
            {"id": "en_revision", "descripcion": "Expediente en revisión"},
            {"id": "completo", "descripcion": "Expediente completo"},
            {"id": "incompleto", "descripcion": "Expediente incompleto"},
        ]
    }
