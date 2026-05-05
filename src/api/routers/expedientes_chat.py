"""Router para el chat IA sobre expedientes docentes."""

from __future__ import annotations

import re
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import verify_token
from src.core.logger import get_agent_logger
from src.prompts.chat_expediente import SYSTEM_PROMPT_CHAT
from src.services.llm import create_llm_provider
from src.services.llm_service import LlmService
from src.services.mongo_service import MongoService

logger = get_agent_logger("api")

router = APIRouter(prefix="/expedientes")

_MAX_DOCUMENTOS_CONTEXTO = 8
_MAX_OCR_POR_DOC = 500
_MAX_TOKENS_RESPUESTA = 300
_TEMPERATURE = 0.2
_MAX_CONTEXTO_CHARS = 6000


class ChatRequest(BaseModel):
    pregunta: str = Field(..., min_length=1, max_length=500)


@router.post("/{cedula}/chat")
async def chat_expediente(
    cedula: str,
    body: ChatRequest,
    payload: dict = Depends(verify_token),
):
    """Responde una pregunta sobre el expediente de un docente usando IA.

    Carga los datos del docente y sus documentos desde MongoDB, construye
    un contexto estructurado y delega al LLM configurado (OpenRouter u Ollama).

    Returns:
        JSON con ``exito``, ``respuesta``, ``cedula``, ``modelo`` y ``latencia_ms``.
    """
    pregunta = body.pregunta.strip()
    if not pregunta:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    mongo = MongoService()

    docente = mongo.docentes.find_one({"docente.cedula": cedula})
    if not docente:
        raise HTTPException(status_code=404, detail=f"Docente con cédula {cedula} no encontrado")

    documentos = list(
        mongo.documentos.find({"docente_cedula": cedula}).limit(_MAX_DOCUMENTOS_CONTEXTO)
    )

    contexto = _armar_contexto(docente, documentos)

    try:
        provider = create_llm_provider()
        service = LlmService(provider)
    except Exception as exc:
        logger.error("Error inicializando LLM para chat: {}", exc)
        raise HTTPException(status_code=503, detail="Servicio LLM no disponible")

    user_prompt = f"Contexto del expediente:\n\n{contexto}\n\nPregunta: {pregunta}"

    inicio = time.perf_counter()
    try:
        respuesta = service.chat(
            SYSTEM_PROMPT_CHAT,
            user_prompt,
            max_tokens=_MAX_TOKENS_RESPUESTA,
            temperature=_TEMPERATURE,
        )
    except RuntimeError as exc:
        logger.error("LLM falló en chat de expediente: {}", exc)
        raise HTTPException(status_code=503, detail="El modelo LLM no respondió")
    except Exception as exc:
        logger.error("Error inesperado en chat de expediente: {}", exc)
        raise HTTPException(status_code=500, detail="Error al procesar la pregunta")
    latencia_ms = round((time.perf_counter() - inicio) * 1000)

    try:
        mongo.db["auditoria"].insert_one({
            "timestamp": datetime.now(),
            "tipo_evento": "chat_expediente_consulta",
            "usuario": payload.get("sub"),
            "docente_cedula": cedula,
            "resultado": "exitoso",
            "detalles": {
                "pregunta_chars": len(pregunta),
                "respuesta_chars": len(respuesta or ""),
                "modelo": provider.model_name,
                "provider": provider.provider_name,
                "latencia_ms": latencia_ms,
                "documentos_en_contexto": len(documentos),
            },
        })
    except Exception as exc:
        logger.warning("No se pudo registrar auditoría de chat: {}", exc)

    return {
        "exito": True,
        "respuesta": respuesta,
        "cedula": cedula,
        "modelo": provider.model_name,
        "latencia_ms": latencia_ms,
    }


def _armar_contexto(docente: dict, documentos: list[dict], max_ocr: int = _MAX_OCR_POR_DOC) -> str:
    """Construye un texto estructurado con los datos del docente y sus documentos.

    Limita el OCR por documento y re-trunca el bloque de documentos si el
    total supera ``_MAX_CONTEXTO_CHARS``.

    Args:
        docente: Documento del docente desde MongoDB.
        documentos: Lista de documentos del docente.
        max_ocr: Máximo de caracteres OCR por documento.

    Returns:
        Texto plano con bloques delimitados para el LLM.
    """
    doc = docente.get("docente", {})
    contacto = doc.get("contacto", {})
    vinc = docente.get("vinculacion_institucional", {})
    comp = docente.get("completitud", {})
    formacion = docente.get("formacion_academica", [])

    lineas: list[str] = []

    lineas.append("=== DOCENTE ===")
    lineas.append(f"Nombre: {doc.get('nombres', '—')} {doc.get('apellidos', '—')}")
    lineas.append(f"Cédula: {doc.get('cedula', '—')}")
    lineas.append(f"Email: {contacto.get('email_personal', '—')}")
    lineas.append(f"Teléfono: {contacto.get('telefono_principal', '—')}")
    lineas.append(f"Nacionalidad: {doc.get('nacionalidad', '—')}")

    lineas.append("\n=== VINCULACIÓN INSTITUCIONAL ===")
    lineas.append(f"Departamento: {vinc.get('departamento', '—')}")
    lineas.append(f"Sede: {vinc.get('sede', '—')}")
    lineas.append(f"Cargo: {vinc.get('cargo_actual', '—')}")
    lineas.append(f"Categoría: {vinc.get('categoria', '—')}")
    lineas.append(f"Dedicación: {vinc.get('dedicacion', '—')}")
    lineas.append(f"Tipo de contratación: {vinc.get('tipo_contratacion', '—')}")

    lineas.append("\n=== COMPLETITUD ===")
    lineas.append(f"Porcentaje: {comp.get('porcentaje', 0)}%")
    faltantes = comp.get("documentos_faltantes", [])
    lineas.append(f"Documentos faltantes: {', '.join(faltantes) if faltantes else 'ninguno'}")

    lineas.append("\n=== FORMACIÓN ACADÉMICA ===")
    if formacion:
        for item in formacion:
            titulo = item.get("titulo", "—")
            inst = item.get("institucion", "—")
            ano = item.get("ano_graduacion", "—")
            lineas.append(f"- {titulo} — {inst} ({ano})")
    else:
        lineas.append("Sin información de formación académica")

    lineas.append(f"\n=== DOCUMENTOS ({len(documentos)}) ===")
    for i, d in enumerate(documentos, 1):
        tipo = d.get("tipo", "—")
        val = d.get("validacion", {})
        estado = val.get("estado", "—") if isinstance(val, dict) else "—"
        lineas.append(f"[{i}] {tipo} (validación: {estado})")

        ocr = d.get("ocr", {}) if isinstance(d.get("ocr"), dict) else {}
        campos = ocr.get("campos_extraidos") or {}
        if campos:
            for clave, valor in campos.items():
                if valor is not None and valor != "":
                    etiqueta = clave.replace("_", " ").title()
                    lineas.append(f"    {etiqueta}: {valor}")

        texto_ocr = ocr.get("texto_completo", "")
        if tipo == "curriculo_vitae" and texto_ocr:
            educacion = _extraer_educacion_cv(texto_ocr)
            if educacion:
                lineas.append("    Formación académica detallada:")
                for edu in educacion:
                    fechas = f" ({edu['fecha_inicio']}–{edu['fecha_fin']})" if edu["fecha_inicio"] else ""
                    inst = f" — {edu['institucion']}" if edu["institucion"] else ""
                    esp = f", {edu['especializacion']}" if edu["especializacion"] else ""
                    lineas.append(f"      - {edu['titulo']}{esp}{fechas}{inst}")
        elif not campos and texto_ocr:
            extracto = texto_ocr[:max_ocr].replace("\n", " ").strip()
            lineas.append(f"    Texto: {extracto}")

    contexto = "\n".join(lineas)

    if len(contexto) > _MAX_CONTEXTO_CHARS and max_ocr > 50:
        return _armar_contexto(docente, documentos, max_ocr=max_ocr // 2)

    return contexto


_RE_SECCION_EDU = re.compile(
    r"Educaci[oó]n\s*\n(.*?)(?=\nPage\s+\d|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_RE_FECHAS = re.compile(r"[\-:]\s*\((\d{4})\s*-\s*(\d{4})\)")
# Líneas que marcan el inicio de una institución (no fragmentos de título)
_RE_UNIVERSIDAD = re.compile(r"^Universidad\b", re.IGNORECASE)


def _extraer_educacion_cv(texto: str) -> list[dict]:
    """Extrae títulos académicos estructurados de la sección Educacion del CV.

    Maneja el word-wrap del PDF: une líneas fragmentadas antes de parsear.
    El formato esperado (LinkedIn PDF) es:
        Universidad X
        Título larg[o partido\nen dos líneas], Especialización : (YYYY - YYYY)

    Devuelve lista de dicts con claves titulo, especializacion, fecha_inicio,
    fecha_fin, institucion. Lista vacía si no se encuentra la sección.
    """
    m = _RE_SECCION_EDU.search(texto)
    if not m:
        return []

    lineas_raw = [l.strip() for l in m.group(1).splitlines() if l.strip()]

    # Primera pasada: si una línea tiene fechas y la anterior no es universidad,
    # la anterior es la segunda mitad del título (word-wrap del PDF) — unirlas.
    lineas: list[str] = []
    for linea in lineas_raw:
        if (
            lineas
            and _RE_FECHAS.search(linea)
            and not _RE_UNIVERSIDAD.match(lineas[-1])
            and not _RE_FECHAS.search(lineas[-1])
        ):
            lineas[-1] = lineas[-1] + " " + linea
        else:
            lineas.append(linea)

    entradas: list[dict] = []
    for i, linea in enumerate(lineas):
        fechas = _RE_FECHAS.search(linea)
        if not fechas:
            continue

        # La línea que precede a la de título (si es universidad) es la institución.
        # Si hay 2+ líneas antes, la de título pudo haberse unido a una de continuación,
        # por lo que la institución puede estar 1 o 2 posiciones atrás.
        institucion = None
        for offset in (1, 2):
            idx = i - offset
            if idx >= 0 and _RE_UNIVERSIDAD.match(lineas[idx]):
                institucion = lineas[idx]
                break

        titulo_raw = _RE_FECHAS.sub("", linea).strip().rstrip(",-: ")
        partes = re.split(r",\s*", titulo_raw, maxsplit=1)
        titulo = partes[0].strip()
        especializacion = partes[1].strip() if len(partes) > 1 else None

        entradas.append({
            "titulo": titulo,
            "especializacion": especializacion,
            "fecha_inicio": fechas.group(1),
            "fecha_fin": fechas.group(2),
            "institucion": institucion,
        })

    return entradas
