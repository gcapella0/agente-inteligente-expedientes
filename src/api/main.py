from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from src.api.routers import config, documentos, estadisticas, expedientes, health, validacion
from src.core.logger import get_agent_logger

logger = get_agent_logger("api")

app = FastAPI(
    title="Expedientes API",
    description="API read-only para expedientes docentes UNEG",
    version="1.2.0",
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(expedientes.router, tags=["Expedientes"])
app.include_router(documentos.router, prefix="/documentos", tags=["Documentos"])
app.include_router(config.router, prefix="/config", tags=["Configuración"])
app.include_router(estadisticas.router, prefix="/estadisticas", tags=["Estadísticas"])
app.include_router(validacion.router, prefix="/validacion", tags=["Validación"])


@app.get("/")
async def root():
    return {"app": "Expedientes API", "version": "1.2.0"}


@app.get("/info")
async def info():
    """Información de la API."""
    return {
        "nombre": "Expedientes API",
        "version": "1.2.0",
        "descripcion": "API read-only para consulta de expedientes docentes UNEG",
        "endpoints_totales": 16,
        "contacto": "soporte@uneg.edu.ve",
        "endpoints": {
            "health": "/health",
            "docentes": "/docentes",
            "buscar_docentes": "/docentes/buscar",
            "expediente": "/expediente/{cedula}",
            "expediente_documentos": "/expediente/{cedula}/documentos",
            "expediente_resumen": "/expediente/{cedula}/resumen",
            "documento": "/documentos/{id}",
            "documento_validacion": "/documentos/{id}/validacion",
            "tipos_documento": "/config/tipos-documento",
            "estados_validacion": "/config/estados-validacion",
            "estados_docente": "/config/estados-docente",
            "estadisticas_expedientes": "/estadisticas/expedientes",
            "estadisticas_documentos": "/estadisticas/documentos",
            "estadisticas_completitud": "/estadisticas/completitud",
            "validacion_expediente": "/validacion/expediente/{cedula}",
        },
        "documentacion": "/docs",
    }


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.warning(f"Error de validación: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=False)
