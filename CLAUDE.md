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
# Run the main entry point (__main__ currently calls test_pipeline(): Watcher → OCR → Classifier)
python -m src.main

# Run all tests (Python 3.12+ required)
pytest tests/ -v

# Run only watcher tests
pytest tests/test_watcher_agent.py -v

# Run only OCR tests
pytest tests/test_ocr.py -v

# Run only classifier tests
pytest tests/test_classifier.py -v

# Run a single test by name
pytest tests/test_ocr.py -k "test_name_here" -v

# Install dependencies (venv assumed active)
pip install -r requirements.txt
```

## Architecture

Multi-agent system for automating teacher dossier ("expediente docente") management at UNEG. WatcherAgent, OcrAgent and ClassifierAgent are implemented. StorageAgent is planned.

### Pipeline

```
WatcherAgent (Gmail IMAP)
  → saves attachments to data/input/{teacher_name}/
    → OcrAgent scans those folders
      → extracts text via docTR
        → ClassifierAgent classifies via LLM (OpenRouter, modelo: openrouter/hunter-alpha)
          → outputs structured JSON with classification
            → Deduplication: SHA-256 hash state file skips already-classified files
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

### ClassifierAgent (`src/agents/classifier_agent.py`) + LlmService (`src/services/llm_service.py`)

- `LlmService` uses the `openai` SDK pointed at OpenRouter (`config.OPENROUTER_BASE_URL`). Default model: `openrouter/hunter-alpha` (config.py); `.env.example` may reference older models — the code default takes precedence. `classify_and_extract(texto_ocr)` sends OCR text with `temperature=0.1`, `max_tokens=1000`, parses JSON response (strips markdown fences via regex), retries up to 3 times with exponential backoff (`delay = 10 * 2^attempt` → 10s, 20s, 40s) on rate limit (429). Returns dict with `valido`, `tipo`, `campos_extraidos`, `confianza_clasificacion`, `modelo_llm`, `tokens_usados`.
- `ClassifierAgent` receives `LlmService` via injection. `classify(ocr_result)` takes an OcrAgent result dict, **extracts `json_ligero` (falling back to `texto_completo`)**, calls LLM, and returns enriched dict with `clasificacion` key added.
- System prompt lives in `src/prompts/classify_document.py` (`CLASSIFY_AND_EXTRACT_PROMPT`). Lists 21 document types (synced with `TipoDocumento` in `src/models/documento.py`) and field extraction rules per type.
- Audit logs: `clasificado`/`ok` for valid, `clasificado`/`rechazado` for invalid, `clasificacion_fallida`/`error` for LLM errors. Detail includes modelo_llm, confianza, campos count, tokens, tiempo_ms.

### Pipeline orchestration (`src/main.py`)

`test_pipeline()` chains Watcher (1 IMAP cycle) → OCR → Classifier with **file-level deduplication**: `data/processed_pipeline.json` stores SHA-256 hashes of already-classified files. Each hash is persisted immediately after classification (crash-resilient). This is separate from WatcherAgent's email-level UID/fingerprint deduplication. Individual agent functions (`test_ocr()`, `test_classifier()`) also exist for isolated testing.

### Configuration (`src/config.py`)

Centralized config from `.env` via `python-dotenv`. Paths resolve from `ROOT_DIR`. Two validators: `validate()` for watcher env vars (MAIL_USER/PASS/HOST), `validate_ocr()` for OCR/storage vars (MONGO_URI, OPENROUTER_API_KEY). `ensure_directories()` creates required data directories (`INPUT_DIR`, `DATA_DIR`). All secrets (API keys, passwords) must live in `.env` only — never hardcode them as defaults in `config.py`. Notable env var: `MAIL_TIMEOUT` (default 30s) controls IMAP connection timeout.

### Logging (`src/core/logger.py`)

Loguru with multiple sinks: stdout, `watcher.log`, `audit.jsonl` (structured JSON, filtered by `audit=True`), and per-agent logs (`ocr.log`, `classifier.log`, `storage.log`, `api.log`, filtered by agent name). Use `get_agent_logger("name")` for agent-specific logging, `audit_log()` for audit events.

### Data models (`src/models/`)

Pydantic v2 models for MongoDB: `DocenteModel` (teacher profile with nested contact, address, education, institutional affiliation, completeness tracking) and `DocumentoModel` (document record with `TipoDocumento` literal, `OcrInfo`, validation state).

### State file backward compatibility

`data/processed_uids.json` supports three formats: legacy list `["uid1"]`, old dict `{"uids": [...]}`, and current `{"uids": [...], "fingerprints": [...]}`. Migration on load.

## Testing patterns

- **151 tests total**: 47 watcher + 57 OCR + 47 classifier, all must pass before merging
- `FakeIMAPClient` mocks `imaplib.IMAP4_SSL` with configurable search results and STORE tracking
- `build_email(subject, body, attachments, from_addr)` creates valid EmailMessage bytes
- `watcher_factory` fixture: patches INPUT_DIR, UID_STATE_FILE, SUBJECT_KEYWORDS, BODY_KEYWORDS. Call as `factory(messages={uid: email_bytes}, processed=[uids], fingerprints=[hashes])`
- `fake_ocr_service` fixture: returns factory that creates `OcrService` with mocked docTR model (no real model download). Call as `factory(words=..., pages=..., language=..., should_fail=...)`
- `sample_input_dir` fixture: creates `tmp_path` with subdirectory structure mimicking `data/input/`. Call as `factory(carpetas={"Docente_A": [("file.pdf", b"content")]})`
- `fake_llm_service` fixture: returns factory that creates `LlmService` with mocked OpenAI client. Call as `factory(response_dict=..., raw_content=..., should_fail=..., fail_exception=...)`. `fake_classifier` wraps it into a `ClassifierAgent`.
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
