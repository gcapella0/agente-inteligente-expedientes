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
# Run the main entry point (__main__ currently calls test_ocr() on data/input/)
python -m src.main

# Run all tests (Python 3.12+ required)
pytest tests/ -v

# Run only watcher tests
pytest tests/test_watcher_agent.py -v

# Run only OCR tests
pytest tests/test_ocr.py -v

# Run a single test by name
pytest tests/test_ocr.py -k "test_name_here" -v

# Install dependencies (venv assumed active)
pip install -r requirements.txt
```

## Architecture

Multi-agent system for automating teacher dossier ("expediente docente") management at UNEG. WatcherAgent and OcrAgent are implemented. StorageAgent is planned.

### Pipeline

```
WatcherAgent (Gmail IMAP)
  → saves attachments to data/input/{teacher_name}/
    → OcrAgent scans those folders
      → extracts text via docTR
        → outputs structured JSON to data/ocr_output/
```

### WatcherAgent (`src/agents/watcher_agent.py`)

Polling loop: connect IMAP → search emails → process each → save to `data/input/{teacher_name}/` → persist state → sleep → repeat.

**Module-level constants are environment-driven and set at import time.** `SUBJECT_KEYWORDS` and `BODY_KEYWORDS` are parsed from comma-separated env vars at module level (not inside the class). Tests must `monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", [...])` on the module — standard env patching won't work.

**Two-level deduplication:** UID-based (skips seen UIDs) + fingerprint-based (SHA-256 of sender+subject+body+attachments catches forwarded duplicates). All validation failures mark the UID as processed to prevent infinite retry loops.

**IMAP search:** Gmail X-GM-RAW first (faster, supports `has:attachment`), falls back to standard IMAP SUBJECT/BODY searches per keyword.

**Known limitation:** Only extracts `text/plain` parts. HTML-only emails won't match body keywords.

### OcrAgent (`src/agents/ocr_agent.py`) + OcrService (`src/services/ocr_service.py`)

- `OcrService` wraps docTR (`python-doctr[torch]`). Initializes `ocr_predictor(pretrained=True)` **once** (model is ~500MB). `process_file(path)` returns dict with `texto_completo`, `json_export`, `json_ligero` (lightweight text-only version), `confianza_promedio`, `paginas`, `idioma_detectado`, `palabras_detectadas`.
- `OcrAgent` receives `OcrService` via injection. `process_directory()` scans `config.INPUT_DIR` subdirectories, processes `.pdf/.jpg/.jpeg/.png` files, ignores `.txt`. Failures are logged via `audit_log()` but don't stop the pipeline.
- Each file result includes `hash_sha256`, `tamano_bytes`, `formato`, `carpeta_origen`, and `ocr_resultado`.

### Configuration (`src/config.py`)

Centralized config from `.env` via `python-dotenv`. Paths resolve from `ROOT_DIR`. Two validators: `validate()` for watcher env vars (MAIL_USER/PASS/HOST), `validate_ocr()` for OCR/storage vars (MONGO_URI, OPENROUTER_API_KEY).

### Logging (`src/core/logger.py`)

Loguru with multiple sinks: stdout, `watcher.log`, `audit.jsonl` (structured JSON, filtered by `audit=True`), and per-agent logs (`ocr.log`, `classifier.log`, `storage.log`, `api.log`, filtered by agent name). Use `get_agent_logger("name")` for agent-specific logging, `audit_log()` for audit events.

### Data models (`src/models/`)

Pydantic v2 models for MongoDB: `DocenteModel` (teacher profile with nested contact, address, education, institutional affiliation, completeness tracking) and `DocumentoModel` (document record with `TipoDocumento` literal, `OcrInfo`, validation state).

### State file backward compatibility

`data/processed_uids.json` supports three formats: legacy list `["uid1"]`, old dict `{"uids": [...]}`, and current `{"uids": [...], "fingerprints": [...]}`. Migration on load.

## Testing patterns

- **91 tests total**: 42 watcher + 49 OCR, all must pass before merging
- `FakeIMAPClient` mocks `imaplib.IMAP4_SSL` with configurable search results and STORE tracking
- `build_email(subject, body, attachments, from_addr)` creates valid EmailMessage bytes
- `watcher_factory` fixture: patches INPUT_DIR, UID_STATE_FILE, SUBJECT_KEYWORDS, BODY_KEYWORDS. Call as `factory(messages={uid: email_bytes}, processed=[uids], fingerprints=[hashes])`
- `fake_ocr_service` fixture: returns factory that creates `OcrService` with mocked docTR model (no real model download). Call as `factory(words=..., pages=..., language=..., should_fail=...)`
- `sample_input_dir` fixture: creates `tmp_path` with subdirectory structure mimicking `data/input/`. Call as `factory(carpetas={"Docente_A": [("file.pdf", b"content")]})`
- Tests use `monkeypatch` extensively because module-level constants are set at import time

## Git and attribution

- **Nunca** agregar líneas `Co-Authored-By` ni menciones de herramientas de IA en los mensajes de commit
- **Nunca** incluir menciones de herramientas de IA en comentarios del código

## Language

The project is in Spanish (comments, variable names in domain context, commit messages). Use Spanish for user-facing text and commit messages.
