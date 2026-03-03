import mimetypes
import signal as signal_module
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.agents.watcher_agent as wa
from src.agents.watcher_agent import WatcherAgent


class FakeIMAPClient:
    """Cliente IMAP mínimo para simular respuestas en los tests."""

    def __init__(self, messages: dict[str, bytes] | None = None, search_uids: list[str] | None = None) -> None:
        self.messages = messages or {}
        self.search_uids = search_uids
        self.store_calls: list[tuple[str, tuple]] = []

    def uid(self, command: str, *args):
        cmd = command.upper()
        if cmd == "FETCH":
            uid = str(args[0])
            raw_email = self.messages.get(uid)
            if raw_email is None:
                return "NO", []
            return "OK", [(uid.encode("utf-8"), raw_email)]
        if cmd == "STORE":
            uid = str(args[0])
            self.store_calls.append((uid, args[1:]))
            return "OK", []
        if cmd == "SEARCH":
            candidate_uids = self.search_uids
            if candidate_uids is None:
                candidate_uids = list(self.messages.keys())
            payload = b" ".join(uid.encode("utf-8") for uid in candidate_uids)
            return "OK", [payload]
        return "NO", []

    def close(self):
        return "OK", []

    def logout(self):
        return "OK", []


def build_email(subject: str, body: str, attachments: list[tuple[str, bytes]] | None = None) -> bytes:
    """Crea un correo simple para alimentar al watcher."""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "postmaster@example.com"
    message["To"] = "watcher@example.com"
    message.set_content(body)

    for filename, content in attachments or []:
        mimetype, _ = mimetypes.guess_type(filename)
        maintype, subtype = ("application", "octet-stream")
        if mimetype:
            maintype, subtype = mimetype.split("/", 1)
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    return message.as_bytes()


@pytest.fixture
def watcher_factory(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_USER", "watcher@example.com")
    monkeypatch.setenv("MAIL_PASS", "secret")
    monkeypatch.setenv("MAIL_HOST", "imap.example.com")
    monkeypatch.setenv("MAIL_FOLDER", "INBOX")

    monkeypatch.setattr(wa, "INPUT_DIR", tmp_path, raising=False)
    monkeypatch.setattr(wa, "BODY_KEYWORDS", [], raising=False)
    uid_state_file = tmp_path / "uids.json"
    monkeypatch.setattr(wa, "UID_STATE_FILE", uid_state_file, raising=False)

    def factory(*, messages: dict[str, bytes] | None = None, processed: set[str] | None = None) -> WatcherAgent:
        initial_processed = set(processed or set())

        def fake_load(self):
            return set(initial_processed)

        monkeypatch.setattr(WatcherAgent, "_load_processed_uids", fake_load)

        watcher = WatcherAgent()
        watcher.processed_uids = set(initial_processed)
        watcher.imap_client = FakeIMAPClient(messages or {})
        return watcher

    return factory


def test_expediente_estandar_crea_carpeta_y_archivos(watcher_factory, tmp_path):
    attachments = [
        ("CV.pdf", b"contenido cv"),
        ("Titulo.docx", b"contenido titulo"),
    ]
    raw_email = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Hola, adjunto documentación",
        attachments=attachments,
    )
    watcher = watcher_factory(messages={"10552": raw_email})

    processed = watcher._process_email("10552")

    case_dir = tmp_path / "Juan_Perez"
    assert processed is True
    assert case_dir.is_dir()
    assert (case_dir / "info_mail_Juan_Perez.txt").is_file()
    assert (case_dir / "CV.pdf").is_file()
    assert (case_dir / "Titulo.docx").is_file()
    assert "10552" in watcher.processed_uids


def test_expediente_sin_nombre_usa_fallback(watcher_factory, tmp_path):
    raw_email = build_email(
        subject="Expediente Docente",
        body="Docente: Juan Pérez",
    )
    watcher = watcher_factory(messages={"20001": raw_email})

    processed = watcher._process_email("20001")

    folders = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert processed is True
    assert len(folders) == 1
    case_dir = folders[0]
    assert case_dir.name.startswith("Expediente_SinNombre_")
    info_files = list(case_dir.glob("info_mail_*.txt"))
    assert len(info_files) == 1
    other_files = [
        path for path in case_dir.iterdir() if path.is_file() and not path.name.startswith("info_mail_")
    ]
    assert other_files == []


def test_correo_ya_procesado_se_omite(watcher_factory, tmp_path):
    raw_email = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Hola",
    )
    watcher = watcher_factory(messages={"99999": raw_email}, processed={"99999"})

    processed = watcher._process_email("99999")

    assert processed is False
    assert list(tmp_path.iterdir()) == []
    assert watcher.processed_uids == {"99999"}


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Expediente Docente - Juan Pérez", "Juan Pérez"),
        ("Expediente Docente – Juan Pérez", "Juan Pérez"),
        ("Expediente Docente: Juan Pérez", "Juan Pérez"),
        ("[EXTERNO] Expediente Docente - Juan Pérez", "Juan Pérez"),
        ("Expediente Docente", None),
    ],
)
def test_extract_teacher_name_variantes(subject, expected):
    assert WatcherAgent._extract_teacher_name(subject) == expected


def test_adjuntos_con_extension_no_soportada_se_ignoran(watcher_factory, tmp_path):
    attachments = [
        ("informe.pdf", b"pdf data"),
        ("datos.xlsx", b"excel data"),
    ]
    raw_email = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Envío dos archivos",
        attachments=attachments,
    )
    watcher = watcher_factory(messages={"30001": raw_email})

    processed = watcher._process_email("30001")

    case_dir = tmp_path / "Juan_Perez"
    assert processed is True
    assert case_dir.is_dir()
    assert (case_dir / "informe.pdf").is_file()
    assert not (case_dir / "datos.xlsx").exists()
    saved_files = {path.name for path in case_dir.iterdir()}
    assert saved_files == {"info_mail_Juan_Perez.txt", "informe.pdf"}


def test_correo_sin_keyword_en_asunto_ni_cuerpo_se_descarta(watcher_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(wa, "BODY_KEYWORDS", ["Certificado", "Hoja de vida", "Curriculum"])
    raw_email = build_email(
        subject="Consulta administrativa - Maria Lopez",
        body="Buen dia, les envio la solicitud.",
    )
    watcher = watcher_factory(messages={"40001": raw_email})

    processed = watcher._process_email("40001")

    assert processed is False
    assert "40001" in watcher.processed_uids
    assert [p for p in tmp_path.iterdir() if p.is_dir()] == []


def test_correo_con_keyword_solo_en_cuerpo_se_acepta(watcher_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(wa, "BODY_KEYWORDS", ["Certificado", "Hoja de vida", "Curriculum"])
    raw_email = build_email(
        subject="Documentos adjuntos - Carlos Ruiz",
        body="Adjunto Curriculum vitae y Certificado de notas.",
    )
    watcher = watcher_factory(messages={"40002": raw_email})

    processed = watcher._process_email("40002")

    case_dir = tmp_path / "Carlos_Ruiz"
    assert processed is True
    assert case_dir.is_dir()
    assert "40002" in watcher.processed_uids


def test_correo_con_keyword_solo_en_asunto_se_acepta(watcher_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(wa, "BODY_KEYWORDS", ["Certificado", "Hoja de vida", "Curriculum"])
    raw_email = build_email(
        subject="Expediente Docente - Ana Torres",
        body="Buen dia, adjunto mis documentos.",
    )
    watcher = watcher_factory(messages={"50001": raw_email})

    processed = watcher._process_email("50001")

    case_dir = tmp_path / "Ana_Torres"
    assert processed is True
    assert case_dir.is_dir()
    assert "50001" in watcher.processed_uids


def test_uid_state_file_corrupto_retorna_set_vacio(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_USER", "watcher@example.com")
    monkeypatch.setenv("MAIL_PASS", "secret")
    monkeypatch.setenv("MAIL_HOST", "imap.example.com")
    monkeypatch.setenv("MAIL_FOLDER", "INBOX")

    uid_state_file = tmp_path / "uids.json"
    uid_state_file.write_text("{ esto no es json valido !!!", encoding="utf-8")
    monkeypatch.setattr(wa, "UID_STATE_FILE", uid_state_file, raising=False)
    monkeypatch.setattr(wa, "INPUT_DIR", tmp_path, raising=False)

    watcher = WatcherAgent()

    assert watcher.processed_uids == set()


def test_sigterm_handler_raises_keyboard_interrupt(watcher_factory, monkeypatch):
    captured_handlers: dict = {}

    def fake_signal(signum, handler):
        captured_handlers[signum] = handler

    monkeypatch.setattr(wa.signal, "signal", fake_signal)

    call_count = {"n": 0}

    def fake_sleep(_):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(wa.time, "sleep", fake_sleep)

    watcher = watcher_factory()
    monkeypatch.setattr(watcher, "_connect_imap", lambda: False)

    watcher.run()

    assert signal_module.SIGTERM in captured_handlers
    handler = captured_handlers[signal_module.SIGTERM]
    with pytest.raises(KeyboardInterrupt):
        handler(signal_module.SIGTERM, None)
