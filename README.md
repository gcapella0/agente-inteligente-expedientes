# Agente Inteligente para la Gestion de Expedientes Docentes - UNEG

Sistema desarrollado en **Python + FastAPI**, diseñado para automatizar la gestion de expedientes docentes mediante **agentes autonomos** capaces de:

- Monitorear correos institucionales y detectar nuevos expedientes.
- Procesar documentos adjuntos mediante **OCR DeepSeek**.
- Indexar y almacenar la informacion relevante en **MongoDB** y **ChromaDB**.

---

## Objetivos del proyecto

1. Automatizar la recepcion y clasificacion de expedientes docentes.
2. Implementar un flujo de agentes con comportamiento autonomo:
   - **WatcherAgent** → supervisa el correo institucional.
   - **OcrAgent** → procesa adjuntos con OCR *(pendiente)*.
   - **StorageAgent** → guarda metadatos y vectores en MongoDB/Chroma *(pendiente)*.
3. Facilitar la busqueda semantica y recuperacion de expedientes en UNEGIA.

---

## Estructura del proyecto

```
├── src/
│   ├── main.py                  # Punto de entrada principal
│   ├── config.py                # Configuracion y variables de entorno
│   ├── agents/
│   │   └── watcher_agent.py     # Agente de monitoreo IMAP
│   └── core/
│       └── logger.py            # Logging con Loguru
├── tests/
│   └── test_watcher_agent.py    # Suite de tests (68 tests)
├── data/
│   ├── input/                   # Expedientes descargados
│   └── processed_uids.json     # Estado de correos procesados
├── logs/
│   └── watcher.log              # Logs de la aplicacion
├── .env                         # Variables de entorno (no versionado)
└── requirements.txt             # Dependencias Python
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

## Configuracion

### Variables de entorno (`.env`)

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
| `INPUT_DIR` | Directorio de salida | `data/input` |
| `PROCESSED_UIDS_FILE` | Archivo de estado | `data/processed_uids.json` |
| `LOG_DIR` | Directorio de logs | `logs` |
| `LOG_LEVEL` | Nivel de logging | `INFO` |

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
python -m src.main
```

### Tests

```bash
pytest tests/test_watcher_agent.py -v
```

La suite de tests incluye **68 pruebas** que cubren:

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

---

## Dependencias principales

| Paquete | Version | Uso |
|---|---|---|
| `fastapi` | 0.115.0 | Framework web (API futura) |
| `uvicorn` | 0.31.0 | Servidor ASGI |
| `python-dotenv` | 1.0.1 | Carga de variables de entorno |
| `loguru` | 0.7.2 | Logging estructurado |
| `pymongo` | 4.10.1 | Conexion a MongoDB *(futuro)* |
| `chromadb` | 0.5.3 | Base de datos vectorial *(futuro)* |
| `pytesseract` | 0.3.13 | OCR con Tesseract *(futuro)* |
| `pillow` | 11.0.0 | Procesamiento de imagenes *(futuro)* |
| `pytest` | 8.3.3 | Framework de testing |

---

## Limitaciones conocidas

- Los correos **solo HTML** (sin parte `text/plain`) no matchean keywords en el cuerpo. El texto HTML se ignora en la comparacion actual.
- El sistema depende de la disponibilidad del servidor IMAP de Gmail.
- La extraccion del nombre del docente requiere que el asunto siga un patron especifico con keyword seguida de separador (`:`, `-`, `–`, `—`).

---

## Roadmap

- [ ] **OcrAgent**: Procesamiento OCR de documentos PDF/imagenes con DeepSeek
- [ ] **StorageAgent**: Almacenamiento de metadatos en MongoDB e indexacion vectorial en ChromaDB
- [ ] **API REST**: Endpoints FastAPI para consulta y busqueda de expedientes
- [ ] **Busqueda semantica**: Recuperacion de expedientes por similitud usando ChromaDB
- [ ] Soporte para extraccion de texto de emails HTML-only
