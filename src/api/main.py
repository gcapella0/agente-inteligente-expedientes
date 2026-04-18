from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from src.api.routers import (
    busqueda,
    config,
    documentos,
    documentos_escribir,
    estadisticas,
    expedientes,
    expedientes_escribir,
    exportacion,
    health,
    validacion,
)
from src.core.logger import get_agent_logger

logger = get_agent_logger("api")

app = FastAPI(
    title="Expedientes API",
    description="API read-write para gestión de expedientes docentes UNEG",
    version="2.0.0",
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(expedientes.router, tags=["Expedientes"])
app.include_router(documentos.router, prefix="/documentos", tags=["Documentos"])
app.include_router(config.router, prefix="/config", tags=["Configuración"])
app.include_router(estadisticas.router, prefix="/estadisticas", tags=["Estadísticas"])
app.include_router(validacion.router, prefix="/validacion", tags=["Validación"])
app.include_router(busqueda.router, prefix="/expedientes", tags=["Búsqueda"])
app.include_router(exportacion.router, prefix="/expedientes", tags=["Exportación"])
app.include_router(expedientes_escribir.router, prefix="/expedientes", tags=["Expedientes (Escritura)"])
app.include_router(documentos_escribir.router, prefix="/documentos", tags=["Documentos (Escritura)"])


@app.get("/")
async def root():
    return {"app": "Expedientes API", "version": "2.0.0"}


@app.get("/info")
async def info():
    """Información de la API."""
    return {
        "nombre": "Expedientes API",
        "version": "2.0.0",
        "descripcion": "API read-write para gestión de expedientes docentes UNEG",
        "fecha_deploy": "2026-04-18T00:00:00Z",
        "endpoints_totales": 26,
        "contacto": "soporte@uneg.edu.ve",
        "capacidades": {
            "lectura": True,
            "escritura": True,
            "auditoria": True,
            "validacion": True,
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
