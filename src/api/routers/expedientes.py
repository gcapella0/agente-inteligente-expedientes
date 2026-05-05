from __future__ import annotations

from base64 import b64decode, b64encode
from pathlib import Path
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from src import config
from src.api.dependencies import verify_token_sse
from src.core.logger import get_agent_logger
from src.services.mongo_service import MongoService

router = APIRouter()
logger = get_agent_logger("api")

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


@router.get("/docentes")
async def list_docentes(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(10, ge=1, le=100, description="Máximo de registros"),
    cursor: Optional[str] = Query(None, description="Cursor opaco para siguiente página"),
):
    """Lista todos los docentes con paginación (skip/limit o cursor)."""
    try:
        mongo = MongoService()
        filtro: dict = {}

        if cursor:
            try:
                cursor_id = ObjectId(b64decode(cursor).decode())
                filtro["_id"] = {"$gt": cursor_id}
            except Exception:
                raise HTTPException(status_code=422, detail="Cursor inválido")

        docentes = list(mongo.docentes.find(filtro).sort([("_id", 1)]).skip(skip).limit(limit + 1))
        tiene_mas = len(docentes) > limit
        if tiene_mas:
            docentes = docentes[:limit]

        cursor_siguiente: Optional[str] = None
        if tiene_mas and docentes:
            cursor_siguiente = b64encode(str(docentes[-1]["_id"]).encode()).decode()

        total = mongo.docentes.count_documents({})
        for doc in docentes:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])

        logger.info(f"Docentes listados: {len(docentes)} (skip={skip}, limit={limit}, cursor={'sí' if cursor else 'no'})")
        return {
            "items": docentes,
            "total": total,
            "skip": skip,
            "limit": limit,
            "cursor_siguiente": cursor_siguiente,
            "tiene_mas": tiene_mas,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al listar docentes: {e}")
        raise HTTPException(status_code=500, detail="Error de base de datos")


@router.get("/docentes/buscar")
async def buscar_docentes(
    q: Optional[str] = Query(None, description="Búsqueda por apellido/nombres"),
    departamento: Optional[str] = Query(None, description="Filtrar por departamento"),
    sede: Optional[str] = Query(None, description="Filtrar por sede"),
    status: Optional[str] = Query(None, description="Filtrar por status (activo|inactivo|en_revision|completo|incompleto)"),
    ordenar: str = Query("apellidos", description="Campo de ordenamiento (apellidos|cedula|completitud|-updated_at)"),
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(10, ge=1, le=100, description="Máximo de registros"),
    cursor: Optional[str] = Query(None, description="Cursor opaco para siguiente página"),
):
    """Búsqueda avanzada de docentes con filtros y cursor-based pagination."""
    try:
        mongo = MongoService()

        filtro: dict = {}
        if q:
            filtro["$or"] = [
                {"docente.apellidos": {"$regex": q, "$options": "i"}},
                {"docente.nombres": {"$regex": q, "$options": "i"}},
                {"docente.cedula": {"$regex": q, "$options": "i"}},
            ]
        if departamento:
            filtro["vinculacion_institucional.departamento"] = departamento
        if sede:
            filtro["vinculacion_institucional.sede"] = sede
        if status:
            filtro["status"] = status

        if cursor:
            try:
                cursor_id = ObjectId(b64decode(cursor).decode())
                filtro["_id"] = {"$gt": cursor_id}
            except Exception:
                raise HTTPException(status_code=422, detail="Cursor inválido")

        sort_field = ordenar.lstrip("-")
        sort_direction = -1 if ordenar.startswith("-") else 1
        _sort_map = {
            "apellidos": "docente.apellidos",
            "cedula": "docente.cedula",
            "completitud": "completitud.porcentaje",
            "updated_at": "updated_at",
        }
        sort_key = _sort_map.get(sort_field, "docente.apellidos")
        sort_tuple = [(sort_key, sort_direction)]

        docentes = list(
            mongo.docentes.find(filtro).sort(sort_tuple).skip(skip).limit(limit + 1)
        )
        tiene_mas = len(docentes) > limit
        if tiene_mas:
            docentes = docentes[:limit]

        cursor_siguiente: Optional[str] = None
        if tiene_mas and docentes:
            cursor_siguiente = b64encode(str(docentes[-1]["_id"]).encode()).decode()

        # Recalcular total sin cursor (total real del filtro base)
        filtro_total = {k: v for k, v in filtro.items() if k != "_id"}
        total = mongo.docentes.count_documents(filtro_total)

        for doc in docentes:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])

        logger.info(f"Búsqueda docentes: q={q}, dept={departamento}, resultados={len(docentes)}")
        return {
            "items": docentes,
            "total": total,
            "skip": skip,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit if limit > 0 else 0,
            "cursor_siguiente": cursor_siguiente,
            "tiene_mas": tiene_mas,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en búsqueda docentes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error de base de datos")


@router.get("/expediente/{cedula}")
async def get_expediente(cedula: str):
    """Obtiene expediente completo (docente + documentos)."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Docente no encontrado: {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        documentos = list(mongo.documentos.find({"docente_cedula": cedula}))

        docente["_id"] = str(docente["_id"])
        for doc in documentos:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])

        logger.info(f"Expediente obtenido: cedula={cedula}, docs={len(documentos)}")
        return {
            "docente": docente,
            "documentos": documentos,
            "total_documentos": len(documentos),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener expediente {cedula}: {e}")
        raise HTTPException(status_code=500, detail="Error de base de datos")


@router.get("/expediente/{cedula}/documentos")
async def listar_documentos(
    cedula: str,
    tipo: Optional[str] = Query(None, description="Filtrar por tipo de documento"),
    validacion: Optional[str] = Query(None, description="Filtrar por estado de validación"),
    incluir_ocr: bool = Query(False, description="Incluir texto OCR completo"),
    ordenar: str = Query("created_at", description="Ordenamiento (created_at|-updated_at)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Lista documentos de un expediente con filtros."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Docente no encontrado para documentos: {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        filtro: dict = {"docente_cedula": cedula}
        if tipo:
            filtro["tipo"] = tipo
        if validacion:
            filtro["validacion.estado"] = validacion

        sort_direction = -1 if ordenar.startswith("-") else 1
        sort_field = ordenar.lstrip("-")
        sort_key = "updated_at" if sort_field == "updated_at" else "created_at"
        sort_tuple = [(sort_key, sort_direction)]

        documentos = list(
            mongo.documentos.find(filtro).sort(sort_tuple).skip(skip).limit(limit)
        )
        total = mongo.documentos.count_documents(filtro)

        for doc in documentos:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            if not incluir_ocr and "ocr" in doc:
                doc["ocr"].pop("texto_completo", None)

        tipos_presentes = {d["tipo"] for d in documentos}
        documentos_incompletos = [t for t in _DOCUMENTOS_REQUERIDOS if t not in tipos_presentes]

        logger.info(f"Documentos listados para {cedula}: {len(documentos)}, faltantes={len(documentos_incompletos)}")
        return {
            "docente_cedula": cedula,
            "items": documentos,
            "total": total,
            "skip": skip,
            "limit": limit,
            "documentos_incompletos": documentos_incompletos,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listando documentos para {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error de base de datos")


@router.get("/expediente/{cedula}/resumen")
async def obtener_resumen(
    cedula: str,
    formato: str = Query("json", description="Formato de respuesta (texto|json)"),
):
    """Obtiene resumen del expediente en formato texto o JSON."""
    try:
        mongo = MongoService()

        docente = mongo.docentes.find_one({"docente.cedula": cedula})
        if not docente:
            logger.warning(f"Docente no encontrado para resumen: {cedula}")
            raise HTTPException(status_code=404, detail="Docente no encontrado")

        documentos = list(mongo.documentos.find({"docente_cedula": cedula}))
        tipos_presentes = {d["tipo"] for d in documentos}
        documentos_incompletos = [t for t in _DOCUMENTOS_REQUERIDOS if t not in tipos_presentes]

        info_docente = docente.get("docente", {})
        nombre_completo = f"{info_docente.get('nombres', '')} {info_docente.get('apellidos', '')}".strip()
        completitud_porcentaje = docente.get("completitud", {}).get("porcentaje", 0)

        if formato == "texto":
            lineas = [
                "=== RESUMEN DE EXPEDIENTE ===",
                f"Número: {docente.get('expediente_numero', 'N/A')}",
                f"Docente: {nombre_completo}",
                f"Cédula: {cedula}",
                f"Departamento: {docente.get('vinculacion_institucional', {}).get('departamento', 'N/A')}",
                f"Status: {docente.get('status', 'N/A')}",
                f"Completitud: {completitud_porcentaje}%",
                "",
                f"Documentos presentes ({len(tipos_presentes)}):",
            ]
            for tipo in sorted(tipos_presentes):
                doc = next((d for d in documentos if d["tipo"] == tipo), None)
                estado = doc.get("validacion", {}).get("estado", "?") if doc else "?"
                lineas.append(f"  ✓ {tipo} ({estado})")

            lineas.append(f"\nDocumentos faltantes ({len(documentos_incompletos)}):")
            if documentos_incompletos:
                for tipo in documentos_incompletos:
                    lineas.append(f"  ✗ {tipo}")
            else:
                lineas.append("  Ninguno")

            lineas.append(f"\nÚltima actualización: {docente.get('updated_at', 'N/A')}")

            logger.info(f"Resumen texto generado para {cedula}")
            return "\n".join(lineas)

        # formato == "json" (default)
        resumen = {
            "numero_expediente": docente.get("expediente_numero"),
            "docente_cedula": cedula,
            "docente_nombre": nombre_completo,
            "status": docente.get("status", "incompleto"),
            "completitud_porcentaje": completitud_porcentaje,
            "documentos_presentes": sorted(tipos_presentes),
            "documentos_faltantes": documentos_incompletos,
            "documentos_requeridos_total": len(_DOCUMENTOS_REQUERIDOS),
            "ultima_actualizacion": docente.get("updated_at"),
        }

        logger.info(f"Resumen JSON generado para {cedula}")
        return resumen

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generando resumen para {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error de base de datos")


@router.get("/expediente/{cedula}/documento/{documento_id}/archivo")
async def servir_archivo_documento(
    cedula: str,
    documento_id: str,
    descargar: bool = Query(False, description="Si true, fuerza descarga (Content-Disposition: attachment)"),
    _: dict = Depends(verify_token_sse),
):
    """Sirve el archivo físico de un documento. Autenticación vía ?token=... (compatible con <img src> e <iframe>)."""
    try:
        oid = ObjectId(documento_id)
    except Exception:
        raise HTTPException(status_code=422, detail="documento_id inválido")

    mongo = MongoService()
    doc = mongo.documentos.find_one({"_id": oid, "docente_cedula": cedula})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    ruta_str = (doc.get("archivo") or {}).get("ruta")
    if not ruta_str:
        raise HTTPException(status_code=404, detail="El documento no tiene archivo asociado")

    archivo_path = Path(ruta_str).resolve()
    storage_root = Path(config.STORAGE_DIR).resolve()

    try:
        archivo_path.relative_to(storage_root)
    except ValueError:
        logger.warning(f"Intento de acceso fuera de STORAGE_DIR: {archivo_path}")
        raise HTTPException(status_code=403, detail="Ruta fuera del almacenamiento permitido")

    if not archivo_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo físico no encontrado")

    formato = (doc.get("archivo") or {}).get("formato", "").lower()
    media_type = {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }.get(formato, "application/octet-stream")

    nombre_original = (doc.get("archivo") or {}).get("nombre_original") or archivo_path.name
    disposition = "attachment" if descargar else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{nombre_original}"'}

    logger.info(f"Sirviendo archivo: cedula={cedula}, doc={documento_id}, descargar={descargar}")
    return FileResponse(str(archivo_path), media_type=media_type, headers=headers)
