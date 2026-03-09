# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the watcher agent
python -m src.main

# Run all tests
pytest tests/test_watcher_agent.py -v

# Run a single test by name
pytest tests/test_watcher_agent.py -k "test_name_here" -v

# Run tests quietly (summary only)
pytest tests/test_watcher_agent.py -q
```

## Architecture

Single-agent system (WatcherAgent) that monitors Gmail via IMAP, filters emails by configurable keywords, and saves attachments to disk. OcrAgent and StorageAgent are planned but not implemented.

### Key flow

`main.py` → `WatcherAgent.run()` → polling loop: connect IMAP → search emails → process each → save to `data/input/{teacher_name}/` → persist state → sleep → repeat.

### Module-level constants are environment-driven and set at import time

`watcher_agent.py` parses `SUBJECT_KEYWORDS` and `BODY_KEYWORDS` from comma-separated env vars at module level (not inside the class). Tests must `monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", [...])` on the module to override them — standard env patching won't work because values are already parsed.

### Two-level deduplication

1. **UID-based**: skips already-seen email UIDs
2. **Fingerprint-based**: SHA-256 of (sender + subject + body + attachment names/content) catches forwarded duplicates with new UIDs

All validation failures mark the UID as processed to prevent infinite retry loops.

### State file backward compatibility

`data/processed_uids.json` supports three formats automatically: legacy list `["uid1"]`, old dict `{"uids": [...]}`, and current `{"uids": [...], "fingerprints": [...]}`. Migration happens on load.

### IMAP search: two-tier strategy

Gmail X-GM-RAW query first (faster, supports `has:attachment`), falls back to standard IMAP SUBJECT/BODY searches per keyword if X-GM-RAW fails.

### Email body extraction

Only extracts `text/plain` parts. HTML-only emails won't match body keywords — this is a known limitation.

## Testing patterns

- `FakeIMAPClient` mocks `imaplib.IMAP4_SSL` with configurable search results and STORE tracking
- `build_email(subject, body, attachments, from_addr)` creates valid EmailMessage bytes
- `watcher_factory` fixture returns a factory function: patches INPUT_DIR, UID_STATE_FILE, SUBJECT_KEYWORDS, BODY_KEYWORDS, and file I/O. Call as `factory(messages={uid: email_bytes}, processed=[uids], fingerprints=[hashes])`
- Tests use `monkeypatch` extensively because module-level constants are set at import time

## Language

The project is in Spanish (comments, variable names in domain context, commit messages). Use Spanish for user-facing text and commit messages.
