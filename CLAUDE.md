# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow and Task Management

### 1. Plan Mode Default
- Activate planning for tasks requiring 3+ steps or architectural decisions
- Stop immediately and replan if complications arise
- Prepare detailed specifications to minimize ambiguity

### 2. Subagent Strategy
- Delegate research, exploration, and parallel analysis to subagents to keep the main context window clean
- Assign one focused task per subagent

### 3. Self-Improvement Loop
- After any correction, update lessons learned and create preventative rules
- Review context before starting work on a new task

### 4. Verification Before Done
- Never mark tasks complete without proving functionality works
- Execute tests, review logs, and demonstrate correctness
- Ask: would a senior engineer approve this?

### 5. Autonomous Bug Fixing
- Address bugs directly: reference logs and failing tests, then implement solutions
- Minimize back-and-forth with the user

### 6. Core Principles
- **Simplicity First**: keep changes minimal and focused
- **No Laziness**: address root causes thoroughly, don't patch symptoms
- **Minimal Impact**: modify only necessary code, avoid unnecessary refactors

### 7. Reutilización antes de implementación
- Antes de escribir cualquier código nuevo, **siempre investigar** si ya existe una librería, paquete o implementación que resuelva el problema
- Priorizar reutilizar soluciones existentes, bien mantenidas y probadas antes de desarrollar desde cero
- Buscar en PyPI, GitHub y la documentación oficial del ecosistema Python
- Solo implementar desde cero cuando no exista una solución adecuada o cuando las dependencias existentes introduzcan complejidad innecesaria

## Commands

```bash
# Run the main entry point (__main__ calls test_pipeline(): Watcher → OCR → Classifier → Storage)
python -m src.main

# Run all tests (Python 3.12+ required)
pytest tests/ -v

# Run only watcher tests
pytest tests/test_watcher_agent.py -v

# Run only OCR tests
pytest tests/test_ocr.py -v

# Run only classifier tests
pytest tests/test_classifier.py -v

# Run only storage tests
pytest tests/test_storage.py -v

# Run only LLM provider tests
pytest tests/test_llm_providers.py -v

# Run a single test by name
pytest tests/test_ocr.py -k "test_name_here" -v

# Install dependencies (venv assumed active)
pip install -r requirements.txt
```

## Architecture

Multi-agent system for automating teacher dossier ("expediente docente") management at UNEG. WatcherAgent, OcrAgent, ClassifierAgent and StorageAgent are implemented.

### Pipeline

```
WatcherAgent (Gmail IMAP)
  → saves attachments to data/input/{teacher_name}/
    → OcrAgent scans those folders
      → extracts text via docTR
        → ClassifierAgent classifies via LLM (OpenRouter or Ollama, selectable via LLM_PROVIDER)
          → outputs structured JSON with classification
            → Deduplication: SHA-256 hash state file skips already-classified files
              → StorageAgent persists in MongoDB and moves files to data/storage/{cedula}/
```

### WatcherAgent (`src/agents/watcher_agent.py`)

Polling loop: connect IMAP → search emails → process each → save to `data/input/{teacher_name}/` → persist state → sleep → repeat.

**Module-level constants are environment-driven and set at import time.** `SUBJECT_KEYWORDS` and `BODY_KEYWORDS` are parsed from comma-separated env vars at module level (not inside the class). Tests must `monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", [...])` on the module — standard env patching won't work.

**Two-level deduplication:** UID-based (skips seen UIDs) + fingerprint-based (SHA-256 of sender+subject+body+attachments catches forwarded duplicates). All validation failures mark the UID as processed to prevent infinite retry loops.

**IMAP search — three-tier strategy:**
1. **X-GM-RAW** (Gmail-specific, fastest): attempts combined query with `has:attachment`. Encodes as UTF-8 bytes. Fails silently on non-Gmail or restricted accounts.
2. **Standard IMAP SUBJECT/BODY**: per-keyword search, **ASCII-only** (`kw.isascii()` filter). Gmail IMAP doesn't support `CHARSET UTF-8` and doesn't do accent-insensitive matching, so non-ASCII keywords (e.g., "Currículum") are skipped at this level.
3. **Date-based fallback** (`SINCE <7-days-ago>`): catches recent emails that ASCII keyword searches miss (e.g., accented subjects). These are filtered locally by `_normalize_text()` in `_process_email()`.

**Accent-insensitive keyword matching:** `_normalize_text()` (module-level function) strips diacritics via `unicodedata.normalize("NFKD")` + filtering combining marks (`category != "Mn"`). Applied in `_process_email` subject/body keyword filtering. `_keyword_variants()` generates accent-stripped variants for IMAP server-side search queries. `_extract_teacher_name` uses original text for regex (preserving accents in names), with generic separator fallback.

**Known limitations:**
- Only extracts `text/plain` parts. HTML-only emails won't match body keywords.
- Gmail IMAP may not support X-GM-RAW on all accounts (silently falls back to standard search).
- Non-ASCII IMAP queries cause `UnicodeEncodeError` in `imaplib` — hence the ASCII-only filter.

### OcrAgent (`src/agents/ocr_agent.py`) + OcrService (`src/services/ocr_service.py`)

- `OcrService` wraps docTR (`python-doctr[torch]`). Initializes `ocr_predictor(pretrained=True)` **once** (model is ~500MB). `process_file(path)` returns dict with `texto_completo`, `json_export`, `json_ligero` (lightweight text-only JSON created by `simplificar_json()` — extracts only text lines per page/block, designed for LLM consumption), `confianza_promedio`, `paginas`, `idioma_detectado`, `palabras_detectadas`.
- `OcrAgent` receives `OcrService` via injection. `process_directory(skip_hashes=set())` scans `config.INPUT_DIR` subdirectories, processes `.pdf/.jpg/.jpeg/.png` files, ignores `.txt`. When `skip_hashes` is provided, computes SHA-256 **before** OCR and skips matching files (used by `test_pipeline()` to avoid re-processing). Failures are logged via `audit_log()` but don't stop the pipeline.
- Each file result includes `hash_sha256`, `tamano_bytes`, `formato`, `carpeta_origen`, and `ocr_resultado`.

### ClassifierAgent (`src/agents/classifier_agent.py`) + LlmService + LLM providers

**Provider architecture** (`src/services/llm/`): plugin pattern with abstract base class.
- `BaseLlmProvider` (ABC): abstract `classify_and_extract(texto_ocr) -> dict` and `health_check() -> dict`. All providers add `latencia_ms` and `provider` fields to the returned dict.
- `OpenRouterProvider`: uses `openai` SDK pointed at OpenRouter. Model rotation on rate limit (primary + fallback models from config). Returns `tokens_usados` from API usage.
- `OllamaProvider`: uses `requests.post` to `POST /api/chat` (chat endpoint, not `/api/generate`). Text truncated to `_PROMPT_MAX_CHARS = 1500` before sending. Options: `num_predict` (default 400), `num_ctx: 2048`, `num_thread: os.cpu_count()`. Returns `tokens_usados=None` (Ollama doesn't report tokens). Recommended models for CPU: `qwen2.5:0.5b` (~10-20s) or `phi3:mini` (~30-60s). **Do not use `mistral` on CPU-only** — exceeds 120s timeout.
- `create_llm_provider()` factory in `llm_factory.py`: reads `LLM_PROVIDER` env var, lazy-imports the provider to avoid circular imports.

**LlmService** (`src/services/llm_service.py`): dual-mode orchestrator.
- With provider injected: `LlmService(create_llm_provider())` — delegates all calls to the provider. `src/main.py` uses this mode so `LLM_PROVIDER` in `.env` is respected.
- Without provider (legacy): `LlmService()` — uses OpenRouter directly with model rotation and retries. Retries up to 3 times on non-JSON response; rotates to next fallback model on rate limit.
- **Backward compat**: `classify_and_extract` uses `getattr(self, "_delegate", None)` — tests that mock `__init__` (bypassing it with `lambda self: None`) never set `_delegate`, so they fall through to the legacy path automatically.
- `_parse_json` static method retained for direct use by tests in `test_classifier.py`.

**ClassifierAgent**: receives `LlmService` via injection. `classify(ocr_result)` extracts `json_ligero` (falling back to `texto_completo`), calls LLM, returns enriched dict with `clasificacion` key added. System prompt: `src/prompts/classify_document.py` (`CLASSIFY_AND_EXTRACT_PROMPT`, ~4400 chars, 21 document types). Audit logs: `clasificado`/`ok`, `clasificado`/`rechazado`, `clasificacion_fallida`/`error`.

### StorageAgent (`src/agents/storage_agent.py`) + MongoService + FileService

- `StorageAgent` receives `MongoService` and `FileService` via injection. `process(classified_result)` runs the full storage pipeline: validates document, extracts and normalizes cédula, checks for hash duplicates, creates or retrieves docente record, inserts documento, updates completitud, and moves the file. Returns dict with `exito`, `accion` ("insert"|"skip"|"error"), `docente_id`, `documento_id`.
- `MongoService` wraps `pymongo`. Collections: `docentes` and `documentos`. Creates indexes on first init (`setup_indexes()`). Key methods: `find_docente_by_cedula`, `find_documento_by_hash`, `insert_docente`, `insert_documento`, `update_completitud`, `generate_expediente_numero` (format: `EXP-{año}-{seq:06d}`), `update_archivo_ruta`. Uses `DocenteModel`/`DocumentoModel` (Pydantic v2) for validation before insert.
- `FileService` manages file movement. `move_to_storage(source_path, cedula, tipo, fecha_emision)` moves files to `config.STORAGE_DIR/{cedula}/{tipo}_{fecha}{ext}`, adding numeric suffix if the target exists. `compute_hash(path)` returns SHA-256 hex. `cleanup_input_directory(dir)` deletes all files and removes directory if empty.
- `_DOCUMENTOS_REQUERIDOS` in `mongo_service.py` lists the 10 required document types for completitud calculation.

### Pipeline orchestration (`src/main.py`)

`test_pipeline()` chains Watcher (1 IMAP cycle) → OCR → Classifier → Storage with **file-level deduplication**: `data/processed_pipeline.json` stores SHA-256 hashes of already-classified files. Each hash is persisted immediately after classification (crash-resilient). This is separate from WatcherAgent's email-level UID/fingerprint deduplication. Both `test_pipeline()` and `test_classifier()` instantiate `LlmService(create_llm_provider())` — the `LLM_PROVIDER` env var is respected at runtime. Individual agent test functions also exist for isolated testing: `test_watcher()`, `test_ocr()`, `test_classifier()`, `test_storage()`.

### Configuration (`src/config.py`)

Centralized config from `.env` via `python-dotenv`. Paths resolve from `ROOT_DIR`. Two validators: `validate()` for watcher env vars (MAIL_USER/PASS/HOST), `validate_ocr()` for OCR/storage vars (MONGO_URI, OPENROUTER_API_KEY). `ensure_directories()` creates `INPUT_DIR`, `DATA_DIR`, `LOG_DIR`, and `STORAGE_DIR`. All secrets (API keys, passwords) must live in `.env` only — never hardcode them as defaults in `config.py`. Notable env vars: `MAIL_TIMEOUT` (default 30s), `MONGO_URI` (default `mongodb://localhost:27017`), `MONGO_DB` (default `expedientes_uneg`), `STORAGE_DIR` (default `data/storage/`), `LLM_PROVIDER` (`"openrouter"` | `"ollama"`), `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS` (default 120), `OLLAMA_NUM_PREDICT` (default 400), `OLLAMA_NUM_THREADS` (default `os.cpu_count()`).

### Logging (`src/core/logger.py`)

Loguru with multiple sinks: stdout, `watcher.log`, `audit.jsonl` (structured JSON, filtered by `audit=True`), and per-agent logs (`ocr.log`, `classifier.log`, `storage.log`, `api.log`, filtered by agent name). Use `get_agent_logger("name")` for agent-specific logging, `audit_log()` for audit events.

### Data models (`src/models/`)

Pydantic v2 models for MongoDB: `DocenteModel` (teacher profile with nested contact, address, education, institutional affiliation, completeness tracking) and `DocumentoModel` (document record with `TipoDocumento` literal, `OcrInfo`, validation state).

### State file backward compatibility

`data/processed_uids.json` supports three formats: legacy list `["uid1"]`, old dict `{"uids": [...]}`, and current `{"uids": [...], "fingerprints": [...]}`. Migration on load.

## Testing patterns

- **182 tests total**: 37 watcher + 50 OCR + 47 classifier + 52 storage + 31 llm_providers, all must pass before merging
- `FakeIMAPClient` mocks `imaplib.IMAP4_SSL` with configurable search results and STORE tracking
- `build_email(subject, body, attachments, from_addr)` creates valid EmailMessage bytes
- `watcher_factory` fixture: patches INPUT_DIR, UID_STATE_FILE, SUBJECT_KEYWORDS, BODY_KEYWORDS. Call as `factory(messages={uid: email_bytes}, processed=[uids], fingerprints=[hashes])`
- `fake_ocr_service` fixture: returns factory that creates `OcrService` with mocked docTR model (no real model download). Call as `factory(words=..., pages=..., language=..., should_fail=...)`
- `sample_input_dir` fixture: creates `tmp_path` with subdirectory structure mimicking `data/input/`. Call as `factory(carpetas={"Docente_A": [("file.pdf", b"content")]})`
- `fake_llm_service` fixture: returns factory that creates `LlmService` with mocked OpenAI client. Call as `factory(response_dict=..., raw_content=..., should_fail=..., fail_exception=...)`. `fake_classifier` wraps it into a `ClassifierAgent`.
- Storage tests use `MagicMock` to mock `MongoService` and `FileService` — no real MongoDB or filesystem required. `CLASSIFIED_RESULT_VALIDO` / `CLASSIFIED_RESULT_NO_VALIDO` constants provide standard test fixtures.
- LLM provider tests (`test_llm_providers.py`): `_ollama_response(content)` builds a mock `/api/chat` response (`{"message": {"content": content}}`). `monkeypatch` on `src.services.llm.ollama_provider.config.*` and `src.services.llm.openrouter_provider.config.*` to patch provider-specific config. OpenAI client is patched via `patch("src.services.llm.openrouter_provider.OpenAI")`.
- Tests use `monkeypatch` extensively because module-level constants are set at import time

## Git branching strategy

- **`main`**: rama de producción, solo recibe merges desde `desarrollo`
- **`desarrollo`**: rama de integración, acumula features terminadas
- **`feature/<nombre-agente>`**: una rama por cada agente/feature, creada desde `desarrollo`
- Cada feature branch debe contener **solo** los archivos y commits de esa feature
- **Nunca** commitear cambios de una feature directamente en `desarrollo`; siempre usar su feature branch
- Flujo: `feature/*` → merge a `desarrollo` → merge a `main`

## Git and attribution

- **Nunca** agregar líneas `Co-Authored-By` ni menciones de herramientas de IA en los mensajes de commit
- **Nunca** incluir menciones de herramientas de IA en comentarios del código

## Language

The project is in Spanish (comments, variable names in domain context, commit messages). Use Spanish for user-facing text and commit messages.
