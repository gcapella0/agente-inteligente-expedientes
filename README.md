# Agente Inteligente para la Gestion de Expedientes Docentes - UNEG

Sistema desarrollado en **Python**, diseñado para automatizar la gestion de expedientes docentes mediante **agentes autonomos** capaces de:

- Monitorear correos institucionales y detectar nuevos expedientes.
- Procesar documentos adjuntos mediante **OCR con docTR** (python-doctr).
- Clasificar documentos automaticamente via **LLM** (OpenRouter o Ollama).
- Comprimir automaticamente PDFs e imagenes antes del almacenamiento.
- Almacenar y organizar la informacion en **MongoDB**.
- Exponer los expedientes a traves de una **API REST** con autenticacion JWT.

---

## Objetivos del proyecto

1. Automatizar la recepcion y clasificacion de expedientes docentes.
2. Implementar un flujo de agentes con comportamiento autonomo:
   - **WatcherAgent** → supervisa el correo institucional.
   - **OcrAgent** → procesa adjuntos con OCR via docTR.
   - **ClassifierAgent** → clasifica documentos y extrae campos via LLM.
   - **StorageAgent** → comprime archivos, persiste metadatos en MongoDB y organiza el almacenamiento.
3. Facilitar la consulta y recuperacion de expedientes desde UNEG.
4. Exponer la informacion a traves de una **API REST FastAPI** con autenticacion JWT, endpoints de lectura/escritura, busqueda de texto completo, exportacion (JSON/XML/CSV) y auditoria admin.

---

## Estructura del proyecto

```
├── src/
│   ├── main.py                      # Punto de entrada: main() (loop continuo) / test_*()
│   ├── config.py                    # Configuracion y variables de entorno
│   ├── agents/
│   │   ├── watcher_agent.py         # Agente de monitoreo IMAP
│   │   ├── ocr_agent.py             # Agente de procesamiento OCR
│   │   ├── classifier_agent.py      # Agente de clasificacion con LLM
│   │   └── storage_agent.py         # Agente de almacenamiento y compresion
│   ├── services/
│   │   ├── ocr_service.py           # Servicio OCR con docTR
│   │   ├── llm_service.py           # Orquestador LLM (OpenRouter / Ollama)
│   │   ├── mongo_service.py         # Servicio de persistencia en MongoDB
│   │   ├── file_service.py          # Servicio de gestion de archivos
│   │   └── llm/
│   │       ├── base_provider.py     # Clase base abstracta para proveedores LLM
│   │       ├── openrouter_provider.py # Proveedor OpenRouter (OpenAI SDK)
│   │       ├── ollama_provider.py   # Proveedor Ollama (requests)
│   │       └── llm_factory.py       # Factory: crea el proveedor segun LLM_PROVIDER
│   ├── models/
│   │   ├── docente.py               # Modelo Pydantic del docente
│   │   ├── documento.py             # Modelo Pydantic de documentos
│   │   └── usuario.py               # Modelo Pydantic de usuario (JWT)
│   ├── core/
│   │   └── logger.py                # Logging con Loguru (audit + por agente)
│   ├── prompts/
│   │   └── classify_document.py     # Prompt de clasificacion para el LLM
│   └── api/
│       ├── main.py                  # App FastAPI, routers, middleware
│       ├── schemas.py               # Modelos Pydantic para respuestas
│       ├── security.py              # JWT: create_access_token, verify_token, bcrypt
│       ├── dependencies.py          # Depends: verify_token, verify_admin
│       └── routers/
│           ├── expedientes.py       # GET docentes, expediente, documentos, resumen
│           ├── expedientes_escribir.py # PUT/DELETE expediente
│           ├── documentos.py        # GET documento, validacion
│           ├── documentos_escribir.py  # POST agregar, PATCH validacion, DELETE
│           ├── busqueda.py          # GET buscar-texto (full-text)
│           ├── exportacion.py       # GET exportar (JSON/XML/CSV)
│           ├── estadisticas.py      # GET expedientes/documentos/completitud
│           ├── validacion.py        # GET validar expediente
│           ├── config.py            # GET tipos-documento/estados
│           ├── auth.py              # POST login/crear-usuario/cambiar-password
│           ├── auditoria.py         # GET auditoria expediente/documento (admin)
│           └── health.py            # GET /health, /, /info
├── tests/
│   ├── test_watcher_agent.py        # Tests del WatcherAgent (47)
│   ├── test_ocr.py                  # Tests del OcrAgent y OcrService (57)
│   ├── test_classifier.py           # Tests del ClassifierAgent y LlmService (48)
│   ├── test_storage.py              # Tests del StorageAgent (83)
│   ├── test_llm_providers.py        # Tests de OpenRouterProvider y OllamaProvider (30)
│   ├── test_api_fase1.py            # Tests API: health, expedientes, documentos (30)
│   ├── test_api_fase2.py            # Tests API: estadisticas y validacion (31)
│   ├── test_api_fase3.py            # Tests API: busqueda, exportacion, paginacion (22)
│   ├── test_api_fase4.py            # Tests API: escritura CRUD (26)
│   └── test_api_fase5.py            # Tests API: autenticacion JWT y auditoria (32)
├── data/
│   ├── input/                       # Expedientes descargados por docente
│   ├── storage/                     # Archivos almacenados por cedula
│   ├── processed_uids.json          # Estado de correos procesados (UIDs + fingerprints)
│   └── processed_pipeline.json      # Hashes de archivos ya clasificados
├── logs/
│   ├── watcher.log                  # Log del WatcherAgent
│   ├── ocr.log                      # Log del OcrAgent
│   ├── classifier.log               # Log del ClassifierAgent
│   ├── storage.log                  # Log del StorageAgent
│   ├── audit.jsonl                  # Log de auditoria estructurado (JSON)
│   └── api.log                      # Log de la API REST
├── .env                             # Variables de entorno (no versionado)
├── .env.example                     # Plantilla de variables de entorno
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
| **Monitoreo IMAP** | Conexion a Gmail con soporte SSL y busqueda en 3 niveles: X-GM-RAW → keywords ASCII → fallback por fecha |
| **Filtrado por keywords** | Busca multiples palabras clave en asunto y cuerpo, con matching accent-insensitive via `_normalize_text()` |
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
SUBJECT_KEYWORD=Certificado, Diploma, Hoja de vida, Curriculum, CV, Titulo, Documentacion, Constancia
BODY_KEYWORD=Certificado, Diploma, Hoja de vida, Curriculum, CV, Titulo, Documentacion, Constancia
```

La busqueda es **case-insensitive** y **accent-insensitive** (ej: "Currículum" coincide con "Curriculum"). Basta con que **una** keyword coincida en el asunto **o** en el cuerpo para que el correo sea aceptado.

### Estrategia de busqueda IMAP

La busqueda de correos usa 3 niveles de fallback:

1. **X-GM-RAW** (Gmail-specific): query combinada con `has:attachment`. Rapido pero no disponible en todas las cuentas.
2. **IMAP estandar SUBJECT/BODY**: busqueda por keyword individual, **solo keywords ASCII** (Gmail no soporta `CHARSET UTF-8` ni matching accent-insensitive en servidor).
3. **Fallback por fecha** (`SINCE <7 dias>`): captura emails recientes que las keywords ASCII no encuentran (ej: asuntos con acentos). Se filtran localmente con `_normalize_text()`.

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
| `json_ligero` | `dict` | JSON simplificado (solo texto por pagina/bloque, diseñado para consumo LLM) |
| `confianza_promedio` | `float` | Confianza promedio (0-1) |
| `paginas` | `int` | Numero de paginas procesadas |
| `idioma_detectado` | `str` | Idioma detectado en el texto |
| `palabras_detectadas` | `int` | Cantidad de palabras extraidas |

### OcrAgent (`src/agents/ocr_agent.py`)

Recibe `OcrService` por inyeccion de dependencias. `process_directory(skip_hashes=set())` escanea los subdirectorios de `data/input/`, procesa archivos de imagen/PDF e ignora archivos `.txt`. Cuando se proporcionan `skip_hashes`, calcula el SHA-256 **antes** del OCR y omite archivos ya procesados.

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

---

## ClassifierAgent + LlmService

Sistema de clasificacion automatica de documentos basado en **LLM** para categorizar los documentos procesados por OCR. Soporta dos proveedores: **OpenRouter** (produccion) y **Ollama** (local/CPU).

### Arquitectura de proveedores (`src/services/llm/`)

Patron plugin con clase base abstracta `BaseLlmProvider`:

- **`OpenRouterProvider`**: usa el SDK de OpenAI apuntado a OpenRouter. Soporta rotacion de modelos ante rate limit (primary + fallback models). Retorna `tokens_usados` desde el API.
- **`OllamaProvider`**: usa `requests.post` al endpoint `/api/chat` de Ollama. Texto truncado a 1500 caracteres antes de enviar. Opciones: `num_predict=400`, `num_ctx=2048`. Modelos recomendados para CPU: `phi3:mini`.
- **`create_llm_provider()`** (factory en `llm_factory.py`): lee `LLM_PROVIDER` del entorno y crea el proveedor correspondiente.

### LlmService (`src/services/llm_service.py`)

Orquestador dual:
- **Con proveedor inyectado** (`LlmService(create_llm_provider())`): delega al proveedor segun `LLM_PROVIDER`. Modo usado en produccion y pipeline.
- **Sin proveedor** (legacy): usa OpenRouter directamente con rotacion de modelos y backoff exponencial: `delay = 10 * 2^intento` → 10s, 20s, 40s (maximo 3 intentos).

**Parametros de inferencia:** `temperature=0.1`, `max_tokens=1000`

**Resultado de `classify_and_extract(texto_ocr)`:**

| Campo | Tipo | Descripcion |
|---|---|---|
| `valido` | `bool` | Si el documento es un tipo reconocido |
| `tipo` | `str` | Tipo de documento (22 tipos definidos) |
| `razon_rechazo` | `str` | Razon si no es valido |
| `campos_extraidos` | `dict` | Campos especificos extraidos segun el tipo |
| `confianza_clasificacion` | `float` | Confianza del modelo (0-1) |
| `modelo_llm` | `str` | Modelo utilizado en la clasificacion |
| `tokens_usados` | `int` | Tokens consumidos (None en Ollama) |

### ClassifierAgent (`src/agents/classifier_agent.py`)

Recibe `LlmService` por inyeccion de dependencias. `classify(ocr_result)` toma el resultado del OcrAgent, extrae `json_ligero` (con fallback a `texto_completo`) y envia al LLM para clasificacion.

**22 tipos de documento soportados:** cedula, RIF, partida de nacimiento, titulo de bachiller, titulo universitario, titulo de postgrado, certificados de notas, acta de grado, fondo negro, nostrificacion, resolucion de nombramiento, evaluacion docente, diplomas (curso/taller/congreso), constancias (trabajo/estudio), carta de recomendacion, curriculo vitae, y otros.

**Auditoria:**
- `clasificado`/`ok`: documento valido clasificado exitosamente
- `clasificado`/`rechazado`: documento no reconocido o irrelevante
- `clasificacion_fallida`/`error`: fallo en la comunicacion con el LLM

---

## StorageAgent

Agente de almacenamiento que recibe el resultado clasificado, comprime el archivo, persiste los metadatos en MongoDB y organiza los archivos en disco.

### Flujo de `process(classified_result)`

```
1. Validar que el documento sea valido y tenga cedula
2. Normalizar cedula (solo digitos)
3. Verificar duplicado por hash SHA-256 en MongoDB
4. Crear o recuperar el registro del docente
5. Comprimir el archivo (PDF con Ghostscript, imagen con Pillow)
6. Insertar documento en MongoDB con metadatos de compresion
7. Actualizar completitud del expediente
8. Mover archivo comprimido a data/storage/{cedula}/{tipo}_{fecha}{ext}
9. Limpiar directorio de entrada si quedo vacio
```

**Retorna:** `{"exito": bool, "accion": "insert"|"skip"|"error", "docente_id": str, "documento_id": str}`

### Compresion de archivos

La compresion se aplica automaticamente antes del almacenamiento:

| Formato | Herramienta | Parametros |
|---|---|---|
| PDF | Ghostscript (`gs`) | `-dPDFSETTINGS=/ebook -r150x150`, calidad equilibrada |
| JPG / JPEG / PNG | Pillow | `quality=85, optimize=True`, conversion a RGB |

- Si la compresion falla (Ghostscript no instalado, error de Pillow), se usa el archivo original como fallback silencioso.
- Si el archivo comprimido resulta **mayor o igual** al original, se descarta y se usa el original.
- Los archivos temporales se guardan en `data/storage/{cedula}/temp/` y se eliminan tras el movimiento.
- Los metadatos de compresion se almacenan en el documento MongoDB: `comprimido`, `metodo_compresion`, `ratio_compresion`, `tamano_original_bytes`, `tamano_almacenado_bytes`.

### MongoService (`src/services/mongo_service.py`)

Servicio de persistencia con `pymongo`. Colecciones: `docentes` y `documentos`.

**Metodos principales:**

| Metodo | Descripcion |
|---|---|
| `find_docente_by_cedula(cedula)` | Busca docente por cedula |
| `find_documento_by_hash(hash)` | Busca documento por SHA-256 (deduplicacion) |
| `insert_docente(data)` | Valida con Pydantic e inserta docente |
| `insert_documento(data)` | Valida con Pydantic e inserta documento |
| `update_completitud(cedula)` | Recalcula porcentaje de completitud del expediente |
| `generate_expediente_numero()` | Genera numero secuencial: `EXP-{año}-{seq:06d}` |
| `update_archivo_ruta(id, ruta)` | Actualiza la ruta del archivo almacenado |
| `enriquecer_docente_desde_cv(cedula, campos)` | Completa el perfil del docente con datos del CV |
| `update_cedula_provisional(prov, real)` | Reemplaza cedula provisional por cedula real |

**Completitud:** calcula el porcentaje de los 10 documentos requeridos presentes en el expediente (excluyendo los rechazados). Almacena tambien la lista de IDs de documentos en `completitud.documentos_ids`.

### FileService (`src/services/file_service.py`)

| Metodo | Descripcion |
|---|---|
| `move_to_storage(src, cedula, tipo, fecha)` | Mueve archivo a `data/storage/{cedula}/{tipo}_{fecha}{ext}` (con sufijo numerico si ya existe) |
| `compute_hash(path)` | Calcula SHA-256 hex del archivo |
| `cleanup_input_directory(dir)` | Elimina todos los archivos y el directorio si queda vacio |

---

## API REST (`src/api/`)

Interfaz HTTP FastAPI sobre MongoDB. Version 2.0.0. Iniciada con:

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI disponible en `http://localhost:8000/docs`.

### Autenticacion JWT (`src/api/security.py`, `src/api/dependencies.py`)

- `POST /auth/login` — devuelve token JWT (8h). Credenciales por defecto: `admin@uneg.edu.ve` / `admin123`.
- `POST /auth/crear-usuario` (solo admin) — crea usuario con rol `admin|usuario|sistema`.
- `POST /auth/cambiar-password` — cambia la contraseña del usuario autenticado.
- Todos los endpoints de escritura (`POST`, `PUT`, `PATCH`, `DELETE`) requieren `Authorization: Bearer <token>`.
- Contraseñas hasheadas con bcrypt (`passlib`). `JWT_SECRET_KEY` en `.env` (cambiar en produccion).

### Endpoints de lectura

| Ruta | Descripcion |
|---|---|
| `GET /expedientes/docentes` | Lista docentes con paginacion por offset o cursor |
| `GET /expedientes/docentes/buscar` | Filtros: nombre, departamento, sede, status |
| `GET /expediente/{cedula}` | Docente + documentos completos |
| `GET /expediente/{cedula}/documentos` | Documentos con filtros tipo/validacion |
| `GET /expediente/{cedula}/resumen` | Resumen en JSON o texto plano |
| `GET /documentos/{id}` | Documento completo por ObjectId |
| `GET /documentos/{id}/validacion` | Estado de validacion del documento |
| `GET /expedientes/buscar-texto` | Full-text search con `$text` de MongoDB |
| `GET /expedientes/{cedula}/exportar` | Exporta expediente como JSON, XML o CSV |
| `GET /estadisticas/expedientes` | Agrupacion de docentes por status/departamento/sede |
| `GET /estadisticas/documentos` | Tipos con menor presencia, distribucion por estado |
| `GET /estadisticas/completitud` | Distribucion por rangos de completitud |
| `GET /validacion/expediente/{cedula}` | Auditoria del expediente (apto/requiere_atencion/critico) |
| `GET /config/tipos-documento` | Catalogo de los 22 tipos de documento |
| `GET /config/estados-validacion` | Catalogo de estados de validacion |
| `GET /config/estados-docente` | Catalogo de estados del docente |
| `GET /health` | Estado del servicio |

### Endpoints de escritura (requieren JWT)

| Ruta | Descripcion |
|---|---|
| `PUT /expedientes/{cedula}` | Actualiza campos del docente (patch parcial) |
| `DELETE /expedientes/{cedula}` | Elimina docente y todos sus documentos (cascada) |
| `POST /documentos/{cedula}/agregar-documento` | Inserta documento y recalcula completitud |
| `PATCH /documentos/{documento_id}/validacion` | Actualiza estado de validacion |
| `DELETE /documentos/{documento_id}` | Elimina documento y recalcula completitud |

### Auditoria admin (solo rol admin)

| Ruta | Descripcion |
|---|---|
| `GET /admin/auditoria/expediente/{cedula}` | Eventos de auditoria de un expediente (filtro por dias, max 100) |
| `GET /admin/auditoria/documento/{documento_id}` | Historial de cambios de un documento |

### Coleccion Bruno

Manual de pruebas en `docs/api/bruno/` — 35 requests organizados en carpetas. Importar en Bruno y seleccionar el environment `local`. El request `auth/login.bru` guarda automaticamente el token en `{{token}}`.

---

## Pipeline completo (`src/main.py`)

`main()` ejecuta el `WatcherAgent` en modo de polling continuo (punto de entrada de produccion).

`test_pipeline()` encadena los 4 agentes con deduplicacion por SHA-256:

```
WatcherAgent (1 ciclo IMAP)
  → descarga adjuntos a data/input/{docente}/
    → OcrAgent
      → extrae texto via docTR
        → ClassifierAgent
          → clasifica y extrae campos via LLM
            → StorageAgent
              → comprime, persiste en MongoDB y mueve a data/storage/{cedula}/
```

**Deduplicacion a nivel de archivo:** `data/processed_pipeline.json` almacena hashes SHA-256 de archivos ya clasificados. Cada hash se persiste inmediatamente tras clasificar (resistente a crashes).

**Funciones de prueba disponibles en `main.py`:**

| Funcion | Descripcion |
|---|---|
| `test_pipeline()` | Pipeline completo: Watcher → OCR → Classifier → Storage |
| `test_ocr()` | Solo OCR sobre `data/input/` |
| `test_classifier()` | OCR + Clasificador (sin Watcher) |
| `test_storage()` | Storage sobre resultados clasificados existentes |
| `test_compression()` | Prueba de compresion sobre archivos en `data/input/` sin pipeline completo |

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
- `Completitud`: seguimiento de completitud del expediente (porcentaje, documentos presentes, faltantes, IDs)

**Estados:** `activo`, `inactivo`, `en_revision`, `completo`, `incompleto`

### DocumentoModel (`src/models/documento.py`)

Registro de documento vinculado a un docente:

- `ArchivoInfo`: metadatos del archivo fisico (nombre, formato, tamaño, hash SHA-256, datos de compresion)
- `OcrInfo`: resultado OCR (texto, confianza, idioma, paginas, campos extraidos)
- `VerificacionVisual`: verificacion visual del documento
- `ValidacionDocumento`: estado de validacion
- `MetadataDocumento`: metadatos adicionales

**22 tipos de documento** definidos en `TipoDocumento`.

**Estados de validacion:** `pendiente`, `aprobado`, `rechazado`, `requiere_revision`

**Campos de compresion en `ArchivoInfo`:**

| Campo | Tipo | Descripcion |
|---|---|---|
| `comprimido` | `bool` | Si el archivo fue comprimido |
| `metodo_compresion` | `str \| None` | `"ghostscript"` o `"pillow"` |
| `ratio_compresion` | `float \| None` | Razon tamaño_comprimido / tamaño_original |
| `tamano_original_bytes` | `int \| None` | Tamaño antes de comprimir |
| `tamano_almacenado_bytes` | `int \| None` | Tamaño del archivo almacenado |

---

## Logging

Sistema de logging estructurado con **Loguru** (`src/core/logger.py`).

| Sink | Descripcion |
|---|---|
| `stdout` | Salida a consola |
| `watcher.log` | Log del WatcherAgent |
| `ocr.log` | Log del OcrAgent |
| `classifier.log` | Log del ClassifierAgent |
| `storage.log` | Log del StorageAgent |
| `audit.jsonl` | Log de auditoria en JSON estructurado (filtrado por `audit=True`) |
| `api.log` | Log de la API REST |

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

#### LLM y clasificacion

| Variable | Descripcion | Valor por defecto |
|---|---|---|
| `LLM_PROVIDER` | Proveedor LLM (`openrouter` o `ollama`) | `openrouter` |
| `OPENROUTER_API_KEY` | API key de OpenRouter | *(requerido si openrouter)* |
| `OPENROUTER_MODEL` | Modelo LLM principal | *(requerido si openrouter)* |
| `OPENROUTER_FALLBACK_MODELS` | Modelos alternativos ante rate limit (coma separados) | *(opcional)* |
| `OPENROUTER_BASE_URL` | URL base de OpenRouter | `https://openrouter.ai/api/v1` |
| `OLLAMA_MODEL` | Modelo Ollama a usar | `phi3:mini` |
| `OLLAMA_TIMEOUT_SECONDS` | Timeout para peticiones a Ollama | `120` |
| `OLLAMA_NUM_PREDICT` | Tokens maximos a generar | `400` |
| `OLLAMA_NUM_THREADS` | Hilos de CPU para inferencia | `os.cpu_count()` |

#### Directorios y almacenamiento

| Variable | Descripcion | Valor por defecto |
|---|---|---|
| `INPUT_DIR` | Directorio de expedientes entrantes | `data/input` |
| `STORAGE_DIR` | Directorio de almacenamiento final | `data/storage` |
| `PROCESSED_UIDS_FILE` | Archivo de estado del watcher | `data/processed_uids.json` |
| `LOG_DIR` | Directorio de logs | `logs` |
| `LOG_LEVEL` | Nivel de logging | `INFO` |

#### Base de datos

| Variable | Descripcion | Valor por defecto |
|---|---|---|
| `MONGO_URI` | URI de conexion a MongoDB | `mongodb://localhost:27017` |
| `MONGO_DB` | Nombre de la base de datos | `expedientes_uneg` |

#### API REST y seguridad

| Variable | Descripcion | Valor por defecto |
|---|---|---|
| `JWT_SECRET_KEY` | Clave secreta para firmar tokens JWT | *(valor inseguro incluido — **cambiar en produccion**)* |

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
- MongoDB en ejecucion local o remoto
- Ghostscript instalado en el sistema (para compresion PDF)
- Ollama instalado (opcional, para clasificacion local sin API)

### Instalacion

```bash
# Clonar el repositorio
git clone https://github.com/gcapella0/agente-inteligente-expedientes.git
cd agente-inteligente-expedientes

# Crear entorno virtual
python -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con las credenciales correspondientes

# Instalar Ghostscript (Ubuntu/Debian)
sudo apt install ghostscript
```

### Ejecucion

```bash
# Modo produccion: WatcherAgent en polling continuo
python -m src.main

# Test de compresion: prueba reduccion de tamaño sobre data/input/
# (Cambiar __main__ en src/main.py para llamar a test_compression())
python -m src.main
```

### Tests

```bash
# Ejecutar todos los tests (406 tests)
pytest tests/ -v

# Solo tests del WatcherAgent
pytest tests/test_watcher_agent.py -v

# Solo tests de OCR
pytest tests/test_ocr.py -v

# Solo tests del ClassifierAgent
pytest tests/test_classifier.py -v

# Solo tests del StorageAgent
pytest tests/test_storage.py -v

# Solo tests de proveedores LLM
pytest tests/test_llm_providers.py -v

# Solo tests de la API REST (Fases 1-5)
pytest tests/test_api_fase1.py tests/test_api_fase2.py tests/test_api_fase3.py tests/test_api_fase4.py tests/test_api_fase5.py -v

# Un test especifico
pytest tests/test_ocr.py -k "test_name_here" -v
```

La suite de tests incluye **406 pruebas** organizadas por agente y fase:

**WatcherAgent (47 tests):**
- Procesamiento basico de emails y creacion de expedientes
- Extraccion de nombres con distintos separadores y formatos
- Filtrado de adjuntos por extension (PDF, JPG, JPEG, mayusculas)
- Matching de keywords en asunto y cuerpo (case-insensitive y accent-insensitive)
- Deduplicacion por UID y por fingerprint
- Correos reenviados (Fwd:) y respondidos (Re:)
- Emails sin asunto, con cuerpo vacio o solo HTML
- Migracion de formatos anteriores del archivo de estado
- Recuperacion ante archivo de estado corrupto
- Busqueda con fallback por fecha y shutdown graceful con SIGTERM

**OcrAgent + OcrService (57 tests):**
- Calculo de confianza promedio y conteo de palabras
- Procesamiento de archivos PDF, JPG, JPEG, PNG
- Validacion de extensiones y manejo de errores
- Escaneo de directorios y procesamiento por lotes
- Extraccion de metadatos y calculo de hash SHA-256
- Generacion de `json_ligero` para consumo LLM
- Deduplicacion por `skip_hashes`
- Casos limite (directorios vacios, archivos inexistentes, fallos de docTR)

**ClassifierAgent + LlmService (48 tests):**
- Clasificacion de documentos por tipo (22 tipos)
- Extraccion de campos especificos por tipo de documento
- Rechazo de documentos irrelevantes con razon
- Parseo de JSON desde respuestas con markdown fences
- Rotacion de modelos LLM ante rate limit
- Reintentos con backoff exponencial
- Fallback de `json_ligero` a `texto_completo`

**StorageAgent (83 tests):**
- Flujo completo de almacenamiento (insert, skip por duplicado, error)
- Normalizacion de cedula (V-, E-, solo digitos)
- Deduplicacion por hash SHA-256 en MongoDB
- Creacion de expediente nuevo vs recuperacion de existente
- Compresion PDF (parametros Ghostscript, FileNotFoundError, timeout, error de retorno)
- Compresion de imagen (JPEG quality=85, conversion PNG→JPEG, error Pillow)
- Fallback a original cuando la compresion falla o el resultado es mayor
- Metadatos de compresion almacenados en MongoDB
- Enriquecimiento del perfil del docente desde curriculo vitae
- Limpieza de directorios de entrada

**Proveedores LLM (30 tests):**
- OpenRouterProvider: clasificacion exitosa, rotacion de modelos, rate limit, error de JSON
- OllamaProvider: clasificacion exitosa, truncado de texto, fallo de conexion, timeout
- Factory `create_llm_provider()`: seleccion por `LLM_PROVIDER`
- Health check de ambos proveedores

**API REST Fase 1 (30 tests):**
- Health, info y raiz
- Listado de docentes con paginacion por offset y cursor
- Detalle de expediente y documentos por cedula
- Resumen en JSON y texto plano
- Detalle y validacion de documento por ObjectId
- Catalogos: tipos de documento, estados de validacion, estados de docente

**API REST Fase 2 (31 tests):**
- Estadisticas de expedientes por status/departamento/sede/completitud
- Estadisticas de documentos: tipos, estados, OCR
- Completitud por rangos y alertas de departamento critico
- Validacion de expediente: estado general, alertas, aptitud para presentacion
- Busqueda de docentes con filtros combinados

**API REST Fase 3 (22 tests):**
- Busqueda full-text con `$text` de MongoDB
- Exportacion de expediente como JSON, XML y CSV
- Cursor-based pagination en listado y busqueda
- Manejo de formatos de exportacion desconocidos (415)

**API REST Fase 4 (26 tests):**
- PUT expediente: actualizacion parcial de campos del docente
- DELETE expediente: eliminacion en cascada con documentos
- POST agregar-documento: insercion y recalculo de completitud
- PATCH validacion: actualizacion de estado y verificacion de argumentos MongoDB
- DELETE documento: eliminacion y recalculo de completitud

**API REST Fase 5 (32 tests):**
- POST login: autenticacion, token JWT, actualizacion de ultimo_login
- POST crear-usuario: creacion con rol, validacion de permisos admin
- POST cambiar-password: verificacion de password actual y actualizacion
- GET auditoria expediente/documento: historial de eventos con filtros
- Proteccion de endpoints: token invalido (401), rol insuficiente (403)

---

## Dependencias principales

| Paquete | Version | Uso |
|---|---|---|
| `fastapi` | 0.115.0 | Framework web (API futura) |
| `uvicorn` | 0.31.0 | Servidor ASGI |
| `python-dotenv` | 1.0.1 | Carga de variables de entorno |
| `pydantic` | 2.9.2 | Modelos de datos y validacion |
| `loguru` | 0.7.2 | Logging estructurado |
| `python-doctr[torch]` | >=0.9.0 | OCR con deep learning |
| `pillow` | 11.0.0 | Compresion y procesamiento de imagenes |
| `pymongo` | 4.10.1 | Conexion a MongoDB |
| `motor` | 3.6.0 | Driver async para MongoDB |
| `openai` | >=1.50.0 | Cliente para OpenRouter |
| `requests` | 2.32.3 | Cliente HTTP (Ollama) |
| `aiohttp` | 3.10.5 | Peticiones HTTP asincronas |
| `email-validator` | 2.2.0 | Validacion de emails (Pydantic) |
| `passlib[bcrypt]` | >=1.7.4 | Hash de contraseñas con bcrypt |
| `python-jose[cryptography]` | >=3.3.0 | Generacion y verificacion de tokens JWT |
| `pytest` | 8.3.3 | Framework de testing |

**Dependencias del sistema:**
- `ghostscript`: compresion de PDFs (paquete `ghostscript` en apt/yum)

---

## Limitaciones conocidas

- Los correos **solo HTML** (sin parte `text/plain`) no matchean keywords en el cuerpo.
- El sistema depende de la disponibilidad del servidor IMAP de Gmail.
- Gmail IMAP no soporta busqueda accent-insensitive en servidor ni `CHARSET UTF-8`. El sistema compensa con busqueda por fecha + filtrado local.
- La extraccion del nombre del docente requiere que el asunto siga un patron especifico con keyword seguida de separador (`:`, `-`, `–`, `—`).
- El modelo OCR de docTR pesa ~500MB y se descarga en la primera ejecucion.
- La compresion PDF requiere Ghostscript instalado en el sistema; sin el, se usa el archivo original sin comprimir.
- Ollama en CPU puede tardar 30-60s por clasificacion con `phi3:mini`. Para produccion se recomienda `LLM_PROVIDER=openrouter`.

---

## Roadmap

- [x] **WatcherAgent**: Monitoreo IMAP, filtrado por keywords, deduplicacion, extraccion de nombre
- [x] **OcrAgent**: Procesamiento OCR de documentos PDF/imagenes con docTR
- [x] **ClassifierAgent**: Clasificacion automatica de documentos via LLM (OpenRouter + Ollama)
- [x] **Pipeline completo**: Watcher → OCR → Classifier → Storage con deduplicacion por SHA-256
- [x] **StorageAgent**: Almacenamiento en MongoDB, compresion de archivos, organizacion por cedula
- [x] **API REST Fase 1**: Health, expedientes, documentos, catalogos (11 endpoints, 30 tests)
- [x] **API REST Fase 2**: Estadisticas, validacion de expediente, busqueda (31 tests)
- [x] **API REST Fase 3**: Busqueda full-text, exportacion JSON/XML/CSV, cursor pagination (22 tests)
- [x] **API REST Fase 4**: Endpoints de escritura CRUD con JWT (26 tests)
- [x] **API REST Fase 5**: Autenticacion JWT, usuarios, auditoria admin (32 tests)
- [ ] **Busqueda semantica**: Recuperacion de expedientes por similitud
- [ ] Soporte para extraccion de texto de emails HTML-only
