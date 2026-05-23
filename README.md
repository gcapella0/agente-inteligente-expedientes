# Agente Inteligente para la Gestión de Expedientes Docentes — UNEG

Sistema desarrollado en Python para automatizar la gestión de expedientes docentes mediante una cadena de agentes autónomos: monitoreo de correo IMAP, OCR, clasificación con LLM y almacenamiento persistente. Se expone a través de una API REST con autenticación JWT y una interfaz web incluida.

---

## Arquitectura

El sistema tiene cuatro agentes que se encadenan en un pipeline lineal:

```
WatcherAgent (IMAP)
  └─▶ data/input/{docente}/
        └─▶ OcrAgent (docTR)
              └─▶ ClassifierAgent (LLM: OpenRouter | Ollama)
                    └─▶ StorageAgent (MongoDB + sistema de archivos)
```

### WatcherAgent — `src/agents/watcher_agent.py`

Polling IMAP contra Gmail (u otro servidor). Descarga adjuntos de correos que coinciden con palabras clave en asunto o cuerpo y los guarda en `data/input/{nombre_docente}/`. Implementa deduplicación en dos niveles: por UID de correo y por huella SHA-256 del contenido (cubre reenvíos). Búsqueda en tres niveles: X-GM-RAW, IMAP estándar ASCII y fallback por fecha con filtrado local insensible a acentos.

### OcrAgent — `src/agents/ocr_agent.py`

Recorre `data/input/` y extrae texto de PDFs e imágenes usando `docTR` (`python-doctr[torch]`). Produce `texto_completo`, `json_ligero` (texto por bloque, optimizado para LLM), confianza promedio, páginas e idioma detectado. El modelo (~500 MB) se carga una sola vez. Salta archivos ya procesados por hash SHA-256.

### ClassifierAgent — `src/agents/classifier_agent.py`

Recibe el resultado OCR y lo envía al LLM configurado. Devuelve un dict con `valido`, `tipo` (uno de 22 tipos), `campos_extraidos`, `confianza_clasificacion` y metadatos del modelo. El prompt del sistema vive en `src/prompts/classify_document.py`.

### StorageAgent — `src/agents/storage_agent.py`

Valida el documento clasificado, extrae y normaliza la cédula, comprueba duplicados por hash, crea o recupera el perfil del docente en MongoDB, inserta el documento, actualiza la completitud del expediente y mueve el archivo. Antes de mover, comprime PDFs con Ghostscript (calidad `ebook`) e imágenes con Pillow (JPEG 85%). Si la compresión falla o produce un archivo más grande, usa el original.

---

## API REST — `src/api/`

FastAPI v2.2.0. Swagger en `/docs`. Interfaz web estática en `/ui`.

| Prefijo | Descripción |
|---|---|
| `/auth` | Login JWT, creación de usuarios, cambio de contraseña |
| `/expedientes` | Listado, búsqueda, detalle, resumen, exportación (JSON/XML/CSV) |
| `/expedientes/{cedula}/chat` | Chat IA sobre el expediente usando el LLM configurado |
| `/documentos` | Consulta, validación, alta, edición y baja de documentos |
| `/estadisticas` | Dashboards de expedientes, documentos y completitud |
| `/validacion` | Auditoría de completitud y estado general del expediente |
| `/agentes` | Estado y ejecución de los 4 agentes (modo independiente o pipeline) |
| `/config/llm` | Proveedor LLM activo (OpenRouter / Ollama), modelo y test de conexión |
| `/config/agentes` | Parámetros de timeout, reintentos y temperatura por agente |
| `/logs/stream` | Streaming de logs en tiempo real (SSE) |
| `/logs/descargar` | Descarga de `audit.jsonl` |
| `/metricas` | KPIs del sistema (documentos, completitud, docentes aptos) |
| `/usuarios` | CRUD de usuarios (solo admin) |
| `/admin/auditoria` | Historial de eventos por expediente o documento (solo admin) |
| `/health` | Estado del servicio |

### Autenticación

JWT con 8 h de expiración. Credenciales por defecto al iniciar por primera vez: `admin@uneg.edu.ve` / `admin123`. Todos los endpoints de escritura requieren token. Los endpoints de auditoría requieren rol `admin`.

---

## Proveedores LLM

El proveedor activo se selecciona con `LLM_PROVIDER` en `.env` o desde la interfaz web (se guarda en MongoDB y tiene precedencia sobre el `.env`).

**OpenRouter** — recomendado para producción. Requiere `OPENROUTER_API_KEY`. Rota automáticamente entre modelos fallback en caso de rate limit.

**Ollama** — para desarrollo local sin costo. Requiere Ollama corriendo en `OLLAMA_BASE_URL`. Modelos recomendados para CPU sin GPU:

| Modelo | RAM aprox. | Tiempo estimado (i5) | Calidad |
|---|---|---|---|
| `phi3:mini` | ~2.2 GB | 30–60 s | Buena |
| `qwen2.5:0.5b` | ~0.8 GB | 10–20 s | Básica |

No usar `mistral` en CPU: supera el timeout de 120 s.

---

## Interfaz web — `src/api/static/`

HTML estático servido por FastAPI en `/ui`. Sin build step; usa Alpine.js 3.x y Tailwind CSS vía CDN.

| Archivo | Función |
|---|---|
| `login.html` | Autenticación JWT |
| `index.html` | Dashboard: KPIs, estado de agentes, mini-log SSE |
| `expedientes.html` | Listado con búsqueda y paginación |
| `expediente.html` | Detalle del expediente, visor de documentos, edición y chat IA |
| `config.html` | Configuración de agentes y proveedor LLM |
| `logs.html` | Visor de logs en tiempo real (SSE) |
| `admin.html` | CRUD de usuarios (solo admin) |

---

## Modelos de datos

**`DocenteModel`** (`src/models/docente.py`) — perfil del docente con datos personales, contacto, dirección, formación académica, vinculación institucional y completitud del expediente.

**`DocumentoModel`** (`src/models/documento.py`) — documento con tipo (`TipoDocumento`, 22 valores), resultado OCR, metadatos del archivo, estado de validación y datos de auditoría.

Los 10 documentos requeridos para considerar un expediente completo están listados en `_DOCUMENTOS_REQUERIDOS` dentro de `src/services/mongo_service.py`.

---

## Estructura de carpetas

```
.
├── src/
│   ├── main.py                    # Punto de entrada del WatcherAgent y funciones de prueba
│   ├── config.py                  # Variables de entorno y paths
│   ├── agents/
│   │   ├── watcher_agent.py
│   │   ├── ocr_agent.py
│   │   ├── classifier_agent.py
│   │   └── storage_agent.py
│   ├── api/
│   │   ├── main.py                # App FastAPI, middlewares, startup
│   │   ├── routers/               # Un archivo por grupo de endpoints
│   │   ├── schemas.py             # Modelos Pydantic de respuesta
│   │   ├── security.py            # JWT
│   │   ├── dependencies.py        # Dependencias FastAPI (verify_token, verify_admin)
│   │   └── static/                # Interfaz web (HTML + JS + CSS vía CDN)
│   ├── services/
│   │   ├── ocr_service.py         # Wrapper de docTR
│   │   ├── llm_service.py         # Orquestador LLM (modo provider o legacy)
│   │   ├── mongo_service.py       # Wrapper de pymongo
│   │   ├── file_service.py        # Movimiento y hash de archivos
│   │   └── llm/
│   │       ├── abstract_llm_provider.py
│   │       ├── llm_factory.py     # Mongo-first factory
│   │       ├── openrouter_provider.py
│   │       └── ollama_provider.py
│   ├── models/
│   │   ├── docente.py
│   │   ├── documento.py
│   │   └── usuario.py
│   ├── prompts/
│   │   ├── classify_document.py   # Prompt del clasificador (21 tipos + reglas)
│   │   └── chat_expediente.py     # System prompt del chat IA
│   └── core/
│       └── logger.py              # Loguru: stdout, watcher.log, audit.jsonl, operational.log
├── tests/                         # 504 tests (pytest)
├── data/
│   ├── input/                     # Adjuntos descargados por WatcherAgent
│   └── storage/                   # Archivos comprimidos organizados por cédula
├── logs/                          # watcher.log, audit.jsonl, operational.log, ocr.log, …
├── docs/api/bruno/                # Colección Bruno (47 requests, entorno local)
├── .env.example
├── requirements.txt
└── CLAUDE.md
```

---

## Requisitos

- Python 3.12+
- MongoDB 6+ corriendo localmente o en red
- Ghostscript instalado en el sistema (para compresión de PDFs)
- Ollama (solo si `LLM_PROVIDER=ollama`)

---

## Variables de entorno

Copiar `.env.example` a `.env` y completar los valores. Las variables marcadas como requeridas deben estar presentes antes de iniciar.

### Seguridad

| Variable | Descripción | Requerida |
|---|---|---|
| `JWT_SECRET_KEY` | Clave para firmar tokens JWT. Cambiar en producción | Sí |

### Correo IMAP (WatcherAgent)

| Variable | Descripción | Default |
|---|---|---|
| `MAIL_HOST` | Servidor IMAP | — |
| `MAIL_USER` | Dirección de correo | — |
| `MAIL_PASS` | Contraseña de aplicación (no la del correo) | — |
| `MAIL_SSL` | Usar SSL | `true` |
| `MAIL_FOLDER` | Carpeta IMAP a monitorear | `INBOX` |
| `POLL_INTERVAL_SECONDS` | Segundos entre ciclos de polling | `60` |
| `SUBJECT_KEYWORD` | Palabras clave en asunto (separadas por coma) | — |
| `BODY_KEYWORD` | Palabras clave en cuerpo (separadas por coma) | — |

### MongoDB

| Variable | Descripción | Default |
|---|---|---|
| `MONGO_URI` | URI de conexión | `mongodb://localhost:27017` |
| `MONGO_DB` | Nombre de la base de datos | `expedientes_uneg` |

### LLM — General

| Variable | Descripción | Default |
|---|---|---|
| `LLM_PROVIDER` | Proveedor activo: `openrouter` o `ollama` | `openrouter` |

### LLM — OpenRouter

| Variable | Descripción |
|---|---|
| `OPENROUTER_API_KEY` | API key de OpenRouter |
| `OPENROUTER_MODEL` | Modelo principal (ej. `minimax/minimax-m2.5:free`) |
| `OPENROUTER_FALLBACK_MODELS` | Modelos fallback separados por coma |
| `OPENROUTER_BASE_URL` | URL base de la API (default: `https://openrouter.ai/api/v1`) |

### LLM — Ollama

| Variable | Descripción | Default |
|---|---|---|
| `OLLAMA_BASE_URL` | URL del servidor Ollama | `http://localhost:11434` |
| `OLLAMA_MODEL` | Modelo a usar (ej. `phi3:mini`) | `mistral` |
| `OLLAMA_TIMEOUT_SECONDS` | Timeout por petición en segundos | `120` |
| `OLLAMA_NUM_PREDICT` | Máximo de tokens en la respuesta | `1000` |
| `OLLAMA_NUM_THREADS` | Hilos de CPU (por defecto todos los disponibles) | — |

### Opcionales

| Variable | Descripción | Default |
|---|---|---|
| `INPUT_DIR` | Directorio de entrada para adjuntos | `data/input` |
| `STORAGE_DIR` | Directorio de almacenamiento final | `data/storage` |
| `LOG_DIR` | Directorio de logs | `logs` |
| `LOG_LEVEL` | Nivel de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `AUDIT_RETENTION` | Retención del audit log | `90 days` |
| `AUDIT_ROTATION` | Rotación del audit log | `50 MB` |

---

## Cómo correr en desarrollo

```bash
# 1. Crear entorno virtual e instalar dependencias
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env con los valores reales

# 3. Levantar la API
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# La interfaz web queda disponible en http://localhost:8000/ui
# La documentación Swagger en http://localhost:8000/docs
```

### Comandos de prueba individuales

```bash
# Prueba del pipeline completo (Watcher → OCR → Clasificador → Storage)
python -c "from src.main import test_pipeline; test_pipeline()"

# Solo OCR sobre archivos en data/input/
python -c "from src.main import test_ocr; test_ocr()"

# Solo clasificación (OCR + LLM)
python -c "from src.main import test_classifier; test_classifier()"

# Solo almacenamiento (OCR + LLM + MongoDB)
python -c "from src.main import test_storage; test_storage()"

# Probar compresión sin mover archivos
python -m src.main

# Enriquecer perfiles de docentes desde CVs ya almacenados (utilidad única)
python -c "from src.main import enriquecer_expedientes_desde_cv; enriquecer_expedientes_desde_cv()"

# WatcherAgent en modo continuo (producción)
python -c "from src.main import main; main()"
```

### Tests

```bash
# Suite completa (504 tests, Python 3.12+ requerido)
pytest tests/ -v

# Por módulo
pytest tests/test_watcher_agent.py -v
pytest tests/test_ocr.py -v
pytest tests/test_classifier.py -v
pytest tests/test_storage.py -v
pytest tests/test_llm_providers.py -v
pytest tests/test_api_fase1.py tests/test_api_fase2.py tests/test_api_fase3.py \
       tests/test_api_fase4.py tests/test_api_fase5.py tests/test_api_fase6.py -v
pytest tests/test_expedientes_chat.py -v

# Test específico por nombre
pytest tests/test_ocr.py -k "nombre_del_test" -v
```

### Prueba manual de la API

La colección Bruno está en `docs/api/bruno/` (47 requests). Usar el entorno `local`. El request `login.bru` guarda el token automáticamente en `{{token}}`.
