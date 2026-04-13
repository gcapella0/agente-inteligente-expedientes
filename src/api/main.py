from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.routers import expedientes, health
from src.core.logger import get_agent_logger

logger = get_agent_logger("api")

app = FastAPI(
    title="Expedientes API",
    description="API read-only para expedientes docentes UNEG",
    version="1.0.0",
)

app.include_router(health.router, tags=["health"])
app.include_router(expedientes.router, tags=["expedientes"])


@app.get("/")
async def root():
    return {"app": "Expedientes API", "version": "1.0.0"}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.warning(f"Error de validación: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=False)
