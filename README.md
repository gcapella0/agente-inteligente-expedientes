# Agente Inteligente para la Gestion de Expedientes Docentes - UNEG

Sistema desarrollado en **Python + FastAPI**, diseñado para automatizar la gestion de expedientes docentes mediante **agentes autonomos** capaces de:

- Monitorear correos institucionales y detectar nuevos expedientes.
- Procesar documentos adjuntos mediante **OCR con docTR** (python-doctr).
- Indexar y almacenar la informacion relevante en **MongoDB** y **ChromaDB**.

---

## Objetivos del proyecto

1. Automatizar la recepcion y clasificacion de expedientes docentes.
2. Implementar un flujo de agentes con comportamiento autonomo:
   - **WatcherAgent** → supervisa el correo institucional.
   - **OcrAgent** → procesa adjuntos con OCR via docTR.
   - **StorageAgent** → guarda metadatos y vectores en MongoDB/Chroma *(pendiente)*.
3. Facilitar la busqueda semantica y recuperacion de expedientes en UNEGIA.

---

## Estructura del proyecto

```
├── src/
│   ├── main.py                      # Punto de entrada principal
│   ├── config.py                    # Configuracion y variables de entorno
│   ├── agents/
│   │   ├── watcher_agent.py         # Agente de monitoreo IMAP
│   │   └── ocr_agent.py            # Agente de procesamiento OCR
│   ├── services/
│   │   └── ocr_service.py          # Servicio OCR con docTR
│   ├── models/
│   │   ├── docente.py              # Modelo Pydantic del docente
│   │   └── documento.py            # Modelo Pydantic de documentos
│   ├── core/
│   │   └── logger.py               # Logging con Loguru (audit + por agente)
│   ├── api/                         # Endpoints FastAPI (pendiente)
│   └── prompts/                     # Prompts para LLM (pendiente)
├── tests/
│   ├── test_watcher_agent.py        # Tests del WatcherAgent
│   └── test_ocr.py                  # Tests del OcrAgent y OcrService
├── data/
│   ├── input/                       # Expedientes descargados por docente
│   ├── ocr_output/                  # Resultados OCR en JSON
│   ├── storage/                     # Almacenamiento futuro
│   └── processed_uids.json         # Estado de correos procesados
├── logs/
│   ├── watcher.log                  # Log del WatcherAgent
│   ├── ocr.log                      # Log del OcrAgent
│   ├── audit.jsonl                  # Log de auditoria estructurado (JSON)
│   ├── classifier.log               # Log del ClassifierAgent (futuro)
│   ├── storage.log                  # Log del StorageAgent (futuro)
│   └── api.log                      # Log de la API (futuro)
├── .env                             # Variables de entorno (no versionado)
├── CLAUDE.md                        # Directrices para Claude Code
└── requirements.txt                 # Dependencias Python
```

---

## WatcherAgent

Agente principal que monitorea una casilla de correo Gmail via IMAP y procesa los correos entrantes relacionados con expedientes docentes.

### Flujo de procesamiento

```
1. Conectar al servidor IMAP (Gmail)
2. Buscar correos que coincidan con keywords + tengan adjuntos
3. Para cada correo:
   a. Verificar si ya fue procesado (por UID)
   b. Decodificar email (asunto, cuerpo, adjuntos)
   c. Verificar duplicado por contenido (fingerprint SHA-256)
   d. Validar keywords en asunto O cuerpo
   e. Validar adjuntos requeridos (PDF/JPG)
   f. Extraer nombre del docente del asunto
   g. Crear carpeta del expediente
   h. Guardar cuerpo del email en archivo .txt
   i. Guardar adjuntos
   j. Marcar como leido en Gmail
   k. Registrar UID + fingerprint en archivo de estado
```

### Funcionalidades clave

| Funcionalidad | Descripcion |
|---|---|
| **Monitoreo IMAP** | Conexion a Gmail con soporte SSL y busqueda por X-GM-RAW con fallback a IMAP estandar |
| **Filtrado por keywords** | Busca multiples palabras clave tanto en asunto como en cuerpo del email |
| **Validacion de adjuntos** | Solo acepta archivos PDF (`.pdf`) y JPG (`.jpg`, `.jpeg`) |
| **Deduplicacion por UID** | Omite correos ya procesados por su identificador unico |
| **Deduplicacion por fingerprint** | Hash SHA-256 de remitente + asunto + cuerpo + adjuntos para detectar reenvios |
| **Extraccion de nombre** | Parseo del nombre del docente desde el asunto usando regex y keywords |
| **Nombres de archivo seguros** | Normalizacion Unicode y sanitizado de caracteres especiales |
| **Persistencia de estado** | Archivo JSON con UIDs y fingerprints, compatible con formatos anteriores |
| **Shutdown graceful** | Manejo de SIGTERM para cierre controlado |

### Deduplicacion por fingerprint

Cuando un correo es reenviado (Fwd:), Gmail le asigna un nuevo UID. Para evitar procesar el mismo contenido dos veces, se calcula un hash SHA-256 que incluye:

- **Remitente** (`From`): permite procesar el mismo contenido enviado por distintas personas.
- **Asunto** (sin prefijos Fwd:/Re:)
- **Cuerpo** del email (text/plain)
- **Nombre y contenido** de cada adjunto

Si el fingerprint ya existe en el estado, el correo se omite y se registra como duplicado.

### Keywords

Las keywords se configuran como listas separadas por comas en el archivo `.env`:

```env
SUBJECT_KEYWORD=Certificado, Diploma, Hoja de vida, Curriculum, CV, Titulo, Documentacion, Voucher de pago, Constancia
BODY_KEYWORD=Certificado, Diploma, Hoja de vida, Curriculum, CV, Titulo, Documentacion, Voucher de pago, Constancia
```

La busqueda es **case-insensitive** y basta con que **una** keyword coincida en el asunto **o** en el cuerpo para que el correo sea aceptado.

---

## OcrAgent + OcrService

Sistema de reconocimiento optico de caracteres basado en **docTR** (`python-doctr[torch]`) para extraer texto de los documentos adjuntos descargados por el WatcherAgent.

### OcrService (`src/services/ocr_service.py`)

Servicio que encapsula docTR. Inicializa `ocr_predictor(pretrained=True)` **una sola vez** (el modelo pesa ~500MB).

**Formatos soportados:** `.pdf`, `.jpg`, `.jpeg`, `.png`

**Resultado de `process_file(path)`:**

| Campo | Tipo | Descripcion |
|---|---|---|
| `texto_completo` | `str` | Texto extraido completo |
| `json_export` | `dict` | Exportacion estructurada de docTR |
| `confianza_promedio` | `float` | Confianza promedio (0-1) |
| `paginas` | `int` | Numero de paginas procesadas |
| `idioma_detectado` | `str` | Idioma detectado en el texto |
| `palabras_detectadas` | `int` | Cantidad de palabras extraidas |

### OcrAgent (`src/agents/ocr_agent.py`)

Recibe `OcrService` por inyeccion de dependencias. `process_directory()` escanea los subdirectorios de `data/input/`, procesa archivos de imagen/PDF e ignora archivos `.txt`.

**Resultado por archivo:**

| Campo | Descripcion |
|---|---|
| `archivo_path` | Ruta completa del archivo |
| `archivo_nombre` | Nombre del archivo |
| `carpeta_origen` | Carpeta del docente |
| `formato` | Extension del archivo |
| `tamano_bytes` | Tamaño en bytes |
| `hash_sha256` | Hash SHA-256 del contenido |
| `ocr_resultado` | Resultado del OCR (o `null` si falla) |

Los resultados se exportan como JSON a `data/ocr_output/{carpeta}/{archivo}.json`. Los errores se registran via `audit_log()` pero no detienen el pipeline.

---

## Modelos de datos

Modelos Pydantic v2 diseñados para almacenamiento en MongoDB.

### DocenteModel (`src/models/docente.py`)

Perfil del docente con modelos anidados:

- `InfoDocente`: datos personales (cedula, nombre, apellido, fecha de nacimiento, genero)
- `ContactoDocente`: informacion de contacto (email, telefono)
- `DireccionDocente`: direccion fisica
- `FormacionAcademica`: titulos y formacion (titulo, institucion, fecha, area)
- `VinculacionInstitucional`: afiliacion a UNEG (departamento, cargo, fecha de ingreso)
- `Completitud`: seguimiento de completitud del expediente

**Estados:** `activo`, `inactivo`, `en_revision`, `completo`, `incompleto`

### DocumentoModel (`src/models/documento.py`)

Registro de documento vinculado a un docente:

- `ArchivoInfo`: metadatos del archivo (nombre, formato, tamaño, hash)
- `OcrInfo`: resultado OCR (texto, confianza, idioma, paginas)
- `VerificacionVisual`: verificacion visual del documento
- `ValidacionDocumento`: estado de validacion
- `MetadataDocumento`: metadatos adicionales

**21 tipos de documento** definidos en `TipoDocumento` (cedula, titulo, constancia, etc.)

**Estados de validacion:** `pendiente`, `aprobado`, `rechazado`, `requiere_revision`

---

## Logging

Sistema de logging estructurado con **Loguru** (`src/core/logger.py`).

| Sink | Descripcion |
|---|---|
| `stdout` | Salida a consola |
| `watcher.log` | Log del WatcherAgent |
| `ocr.log` | Log del OcrAgent |
| `audit.jsonl` | Log de auditoria en JSON estructurado (filtrado por `audit=True`) |
| `classifier.log` | Log del ClassifierAgent (futuro) |
| `storage.log` | Log del StorageAgent (futuro) |
| `api.log` | Log de la API (futuro) |

- `get_agent_logger("nombre")`: obtiene logger filtrado por agente
- `audit_log(evento, datos)`: registra eventos de auditoria en `audit.jsonl`

---

## Configuracion

### Variables de entorno (`.env`)

#### WatcherAgent

| Variable | Descripcion | Valor por defecto |
|---|---|---|
| `MAIL_HOST` | Servidor IMAP | `imap.gmail.com` |
| `MAIL_USER` | Usuario de correo | *(requerido)* |
| `MAIL_PASS` | Contrasena de aplicacion | *(requerido)* |
| `MAIL_SSL` | Usar conexion SSL | `true` |
| `MAIL_FOLDER` | Carpeta a monitorear | `INBOX` |
| `POLL_INTERVAL_SECONDS` | Intervalo de sondeo (segundos) | `60` |
| `SUBJECT_KEYWORD` | Keywords para asunto (separadas por coma) | `Expediente Docente` |
| `BODY_KEYWORD` | Keywords para cuerpo (separadas por coma) | `Expediente Docente` |

#### Directorios y estado

| Variable | Descripcion | Valor por defecto |
|---|---|---|
| `INPUT_DIR` | Directorio de expedientes | `data/input` |
| `PROCESSED_UIDS_FILE` | Archivo de estado | `data/processed_uids.json` |
| `LOG_DIR` | Directorio de logs | `logs` |
| `LOG_LEVEL` | Nivel de logging | `INFO` |
| `STORAGE_DIR` | Directorio de almacenamiento | `data/storage` |

#### OCR y servicios externos

| Variable | Descripcion | Valor por defecto |
|---|---|---|
| `MONGO_URI` | URI de conexion a MongoDB | `mongodb://localhost:27017` |
| `MONGO_DB` | Nombre de la base de datos | `expedientes_uneg` |
| `OPENROUTER_API_KEY` | API key de OpenRouter | *(requerido para OCR)* |
| `OPENROUTER_MODEL` | Modelo LLM a utilizar | `meta-llama/llama-3.1-8b-instruct:free` |
| `OPENROUTER_BASE_URL` | URL base de OpenRouter | `https://openrouter.ai/api/v1` |
| `AUDIT_RETENTION` | Retencion de logs de auditoria | `90 days` |
| `AUDIT_ROTATION` | Rotacion de logs de auditoria | `50 MB` |

### Archivo de estado (`processed_uids.json`)

```json
{
  "uids": ["10552", "20001"],
  "fingerprints": ["a1b2c3d4e5f6...", "f6e5d4c3b2a1..."]
}
```

Compatible con formatos anteriores (lista de UIDs o diccionario sin fingerprints).

---

## Instalacion y ejecucion

### Requisitos

- Python 3.12+
- Cuenta Gmail con contrasena de aplicacion habilitada

### Instalacion

```bash
# Clonar el repositorio
git clone https://github.com/gcapella/agente-inteligente-expedientes.git
cd agente-inteligente-expedientes

# Crear entorno virtual
python -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con las credenciales correspondientes
```

### Ejecucion

```bash
# Ejecutar el WatcherAgent (modo produccion)
python -m src.main

# Ejecutar prueba de OCR sobre archivos en data/input/
python -m src.main
```

### Tests

```bash
# Ejecutar todos los tests
pytest tests/ -v

# Solo tests del WatcherAgent
pytest tests/test_watcher_agent.py -v

# Solo tests de OCR
pytest tests/test_ocr.py -v

# Un test especifico
pytest tests/test_ocr.py -k "test_name_here" -v
```

La suite de tests incluye **91 pruebas** que cubren:

**WatcherAgent (42 tests):**
- Procesamiento basico de emails y creacion de expedientes
- Extraccion de nombres con distintos separadores y formatos
- Filtrado de adjuntos por extension (PDF, JPG, JPEG, mayusculas)
- Matching de keywords en asunto y cuerpo (case-insensitive)
- Deduplicacion por UID y por fingerprint
- Correos reenviados (Fwd:) y respondidos (Re:)
- Emails sin asunto, con cuerpo vacio o solo HTML
- Migracion de formatos anteriores del archivo de estado
- Recuperacion ante archivo de estado corrupto
- Shutdown graceful con SIGTERM

**OcrAgent + OcrService (49 tests):**
- Calculo de confianza promedio y conteo de palabras
- Procesamiento de archivos PDF, JPG, JPEG, PNG
- Validacion de extensiones y manejo de errores
- Escaneo de directorios y procesamiento por lotes
- Extraccion de metadatos y calculo de hash SHA-256
- Registro de auditoria en exitos y fallos
- Casos limite (directorios vacios, archivos inexistentes, fallos de docTR)

---

## Dependencias principales

| Paquete | Version | Uso |
|---|---|---|
| `fastapi` | 0.115.0 | Framework web (API futura) |
| `uvicorn` | 0.31.0 | Servidor ASGI |
| `python-dotenv` | 1.0.1 | Carga de variables de entorno |
| `pydantic` | 2.9.2 | Modelos de datos y validacion |
| `loguru` | 0.7.2 | Logging estructurado |
| `python-doctr[torch]` | >=0.9.0 | OCR con deep learning (docTR) |
| `pillow` | 11.0.0 | Procesamiento de imagenes |
| `pymongo` | 4.10.1 | Conexion a MongoDB |
| `motor` | 3.6.0 | Driver async para MongoDB |
| `openai` | >=1.50.0 | Cliente para APIs LLM (OpenRouter) |
| `requests` | 2.32.3 | Peticiones HTTP |
| `aiohttp` | 3.10.5 | Peticiones HTTP asincronas |
| `email-validator` | 2.2.0 | Validacion de emails (Pydantic) |
| `pytest` | 8.3.3 | Framework de testing |

---

## Limitaciones conocidas

- Los correos **solo HTML** (sin parte `text/plain`) no matchean keywords en el cuerpo. El texto HTML se ignora en la comparacion actual.
- El sistema depende de la disponibilidad del servidor IMAP de Gmail.
- La extraccion del nombre del docente requiere que el asunto siga un patron especifico con keyword seguida de separador (`:`, `-`, `–`, `—`).
- El modelo OCR de docTR pesa ~500MB y se descarga en la primera ejecucion.

---

## Roadmap

- [x] **WatcherAgent**: Monitoreo IMAP, filtrado por keywords, deduplicacion, extraccion de nombre
- [x] **OcrAgent**: Procesamiento OCR de documentos PDF/imagenes con docTR
- [ ] **StorageAgent**: Almacenamiento de metadatos en MongoDB e indexacion vectorial en ChromaDB
- [ ] **API REST**: Endpoints FastAPI para consulta y busqueda de expedientes
- [ ] **Busqueda semantica**: Recuperacion de expedientes por similitud usando ChromaDB
- [ ] Soporte para extraccion de texto de emails HTML-only
