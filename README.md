# Agente Inteligente para la Gestión de Expedientes Docentes – UNEG

Sistema desarrollado en **Python + FastAPI**, diseñado para automatizar la gestión de expedientes docentes mediante **agentes autónomos** capaces de:
- Monitorear correos institucionales y detectar nuevos expedientes.
- Procesar documentos adjuntos mediante **OCR DeepSeek**.
- Indexar y almacenar la información relevante en **MongoDB** y **ChromaDB**.

---

## Objetivos del proyecto

1. Automatizar la recepción y clasificación de expedientes docentes.
2. Implementar un flujo de agentes con comportamiento autónomo:
   - **WatcherAgent** → supervisa el correo institucional.
   - **OcrAgent** → procesa adjuntos con OCR.
   - **StorageAgent** → guarda metadatos y vectores en MongoDB/Chroma.
3. Facilitar la búsqueda semántica y recuperación de expedientes en UNEGIA.

---

## Estructura del proyecto

src/
├── api/ → Rutas, modelos y controladores FastAPI
├── agents/ → Agentes autónomos
├── services/ → Conexiones (mail, OCR, Mongo, Chroma)
├── core/ → Configuración, logs, utilidades y seguridad
├── data/ → Archivos de entrada, procesados y resultados
└── tests/ → Pruebas unitarias e integracion
