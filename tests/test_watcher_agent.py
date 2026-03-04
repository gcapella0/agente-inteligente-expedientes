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


def build_email(
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]] | None = None,
    from_addr: str = "postmaster@example.com",
) -> bytes:
    """Crea un correo simple para alimentar al watcher."""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
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
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", ["Expediente Docente"], raising=False)
    monkeypatch.setattr(wa, "BODY_KEYWORDS", [], raising=False)
    uid_state_file = tmp_path / "uids.json"
    monkeypatch.setattr(wa, "UID_STATE_FILE", uid_state_file, raising=False)

    def factory(
        *,
        messages: dict[str, bytes] | None = None,
        processed: set[str] | None = None,
        fingerprints: set[str] | None = None,
    ) -> WatcherAgent:
        initial_processed = set(processed or set())
        initial_fingerprints = set(fingerprints or set())

        def fake_load(self):
            return set(initial_processed), set(initial_fingerprints)

        monkeypatch.setattr(WatcherAgent, "_load_state", fake_load)

        watcher = WatcherAgent()
        watcher.processed_uids = set(initial_processed)
        watcher.processed_fingerprints = set(initial_fingerprints)
        watcher.imap_client = FakeIMAPClient(messages or {})
        return watcher

    return factory


def test_expediente_estandar_crea_carpeta_y_archivos(watcher_factory, tmp_path):
    attachments = [
        ("CV.pdf", b"contenido cv"),
        ("Foto.jpg", b"contenido foto"),
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
    assert (case_dir / "Foto.jpg").is_file()
    assert "10552" in watcher.processed_uids


def test_expediente_sin_nombre_usa_fallback(watcher_factory, tmp_path):
    raw_email = build_email(
        subject="Expediente Docente",
        body="Docente: Juan Pérez",
        attachments=[("documento.pdf", b"pdf data")],
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
def test_extract_teacher_name_variantes(subject, expected, monkeypatch):
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", ["Expediente Docente"])
    assert WatcherAgent._extract_teacher_name(subject) == expected


def test_adjuntos_con_extension_no_soportada_se_ignoran(watcher_factory, tmp_path):
    attachments = [
        ("informe.pdf", b"pdf data"),
        ("datos.xlsx", b"excel data"),
        ("notas.docx", b"word data"),
    ]
    raw_email = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Envío archivos",
        attachments=attachments,
    )
    watcher = watcher_factory(messages={"30001": raw_email})

    processed = watcher._process_email("30001")

    case_dir = tmp_path / "Juan_Perez"
    assert processed is True
    assert case_dir.is_dir()
    assert (case_dir / "informe.pdf").is_file()
    assert not (case_dir / "datos.xlsx").exists()
    assert not (case_dir / "notas.docx").exists()
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
        attachments=[("certificado.pdf", b"pdf data")],
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
        attachments=[("titulo.jpg", b"jpg data")],
    )
    watcher = watcher_factory(messages={"50001": raw_email})

    processed = watcher._process_email("50001")

    case_dir = tmp_path / "Ana_Torres"
    assert processed is True
    assert case_dir.is_dir()
    assert "50001" in watcher.processed_uids


def test_correo_sin_adjuntos_pdf_o_jpg_se_descarta(watcher_factory, tmp_path):
    raw_email = build_email(
        subject="Expediente Docente - Pedro García",
        body="Adjunto mis documentos",
    )
    watcher = watcher_factory(messages={"60001": raw_email})

    processed = watcher._process_email("60001")

    assert processed is False
    assert "60001" in watcher.processed_uids
    assert [p for p in tmp_path.iterdir() if p.is_dir()] == []


def test_correo_con_adjuntos_no_validos_se_descarta(watcher_factory, tmp_path):
    raw_email = build_email(
        subject="Expediente Docente - Pedro García",
        body="Adjunto mis documentos",
        attachments=[("datos.xlsx", b"excel"), ("informe.docx", b"word")],
    )
    watcher = watcher_factory(messages={"60002": raw_email})

    processed = watcher._process_email("60002")

    assert processed is False
    assert "60002" in watcher.processed_uids
    assert [p for p in tmp_path.iterdir() if p.is_dir()] == []


def test_correo_con_adjunto_pdf_se_acepta(watcher_factory, tmp_path):
    raw_email = build_email(
        subject="Expediente Docente - María López",
        body="Adjunto mi CV",
        attachments=[("CV.pdf", b"pdf content")],
    )
    watcher = watcher_factory(messages={"60003": raw_email})

    processed = watcher._process_email("60003")

    case_dir = tmp_path / "Maria_Lopez"
    assert processed is True
    assert (case_dir / "CV.pdf").is_file()


def test_correo_con_adjunto_jpg_se_acepta(watcher_factory, tmp_path):
    raw_email = build_email(
        subject="Expediente Docente - María López",
        body="Adjunto mi foto",
        attachments=[("foto.jpg", b"jpg content")],
    )
    watcher = watcher_factory(messages={"60004": raw_email})

    processed = watcher._process_email("60004")

    case_dir = tmp_path / "Maria_Lopez"
    assert processed is True
    assert (case_dir / "foto.jpg").is_file()


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
    assert watcher.processed_fingerprints == set()


def test_correo_reenviado_con_mismo_contenido_se_omite(watcher_factory, tmp_path):
    """Un correo reenviado (UID distinto, mismo contenido) no debe duplicar archivos."""
    attachments = [("CV.pdf", b"contenido cv")]
    raw_email = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Hola, adjunto documentación",
        attachments=attachments,
    )

    # Primer procesamiento: UID 10001
    watcher = watcher_factory(messages={"10001": raw_email})
    assert watcher._process_email("10001") is True

    case_dir = tmp_path / "Juan_Perez"
    assert (case_dir / "CV.pdf").is_file()
    assert len(list(case_dir.iterdir())) == 2  # txt + pdf

    # Segundo procesamiento: UID 10002, mismo contenido
    watcher.imap_client = FakeIMAPClient({"10002": raw_email})
    assert watcher._process_email("10002") is False
    assert "10002" in watcher.processed_uids
    # No se deben haber creado archivos adicionales
    assert len(list(case_dir.iterdir())) == 2


def test_mismo_contenido_distinto_remitente_se_procesa(watcher_factory, tmp_path):
    """Mismo asunto, cuerpo y adjuntos pero de remitentes distintos deben procesarse ambos."""
    attachments = [("CV.pdf", b"contenido cv")]
    email_a = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Adjunto documentación",
        attachments=attachments,
        from_addr="profesorA@example.com",
    )
    email_b = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Adjunto documentación",
        attachments=attachments,
        from_addr="profesorB@example.com",
    )

    watcher = watcher_factory(messages={"30001": email_a})
    assert watcher._process_email("30001") is True

    watcher.imap_client = FakeIMAPClient({"30002": email_b})
    assert watcher._process_email("30002") is True


def test_fingerprint_se_persiste_en_state_file(watcher_factory, tmp_path, monkeypatch):
    """El fingerprint se guarda en el archivo de estado."""
    uid_state_file = tmp_path / "uids.json"
    monkeypatch.setattr(wa, "UID_STATE_FILE", uid_state_file, raising=False)

    raw_email = build_email(
        subject="Expediente Docente - Ana Torres",
        body="Documentos adjuntos",
        attachments=[("titulo.pdf", b"pdf data")],
    )
    watcher = watcher_factory(messages={"20001": raw_email})
    watcher._process_email("20001")

    import json
    state = json.loads(uid_state_file.read_text(encoding="utf-8"))
    assert "fingerprints" in state
    assert len(state["fingerprints"]) == 1


@pytest.mark.parametrize(
    ("keywords", "subject", "expected"),
    [
        (["CV"], "CV - Juan Pérez", "Juan Pérez"),
        (["Titulo"], "Titulo - María López", "María López"),
        (["Certificado"], "Certificado: Ana Torres", "Ana Torres"),
        (["Hoja de vida"], "Hoja de vida – Pedro García", "Pedro García"),
        (["Constancia"], "Constancia - Luis Rodríguez", "Luis Rodríguez"),
        (["CV", "Titulo"], "Titulo - María López", "María López"),
        (["Diploma"], "Diploma", None),
    ],
)
def test_extract_teacher_name_con_keywords_reales(keywords, subject, expected, monkeypatch):
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", keywords)
    assert WatcherAgent._extract_teacher_name(subject) == expected


def test_keyword_corta_en_asunto_matchea(watcher_factory, tmp_path, monkeypatch):
    """Una keyword corta como 'CV' debe matchear en el asunto."""
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", ["CV", "Titulo"])
    raw_email = build_email(
        subject="CV - Juan Pérez",
        body="Adjunto mis documentos.",
        attachments=[("curriculum.pdf", b"pdf data")],
    )
    watcher = watcher_factory(messages={"70001": raw_email})

    processed = watcher._process_email("70001")

    assert processed is True
    case_dir = tmp_path / "Juan_Perez"
    assert case_dir.is_dir()


def test_correo_con_prefijo_fwd_se_acepta(watcher_factory, tmp_path):
    """Un correo reenviado con prefijo Fwd: debe seguir matcheando la keyword."""
    raw_email = build_email(
        subject="Fwd: Expediente Docente - Juan Pérez",
        body="---------- Forwarded message ----------",
        attachments=[("CV.pdf", b"pdf data")],
    )
    watcher = watcher_factory(messages={"70002": raw_email})

    processed = watcher._process_email("70002")

    assert processed is True
    case_dir = tmp_path / "Juan_Perez"
    assert case_dir.is_dir()
    assert (case_dir / "CV.pdf").is_file()


def test_correo_con_prefijo_re_se_acepta(watcher_factory, tmp_path):
    """Un correo con Re: en el asunto debe seguir matcheando."""
    raw_email = build_email(
        subject="Re: Expediente Docente - Ana Torres",
        body="Adjunto nuevamente los documentos.",
        attachments=[("titulo.pdf", b"pdf data")],
    )
    watcher = watcher_factory(messages={"70003": raw_email})

    processed = watcher._process_email("70003")

    assert processed is True


def test_correo_con_multiples_prefijos_fwd_re(watcher_factory, tmp_path):
    """Múltiples Fwd:/Re: no deben impedir el match."""
    raw_email = build_email(
        subject="Fwd: Re: Fwd: Expediente Docente - Carlos Ruiz",
        body="Reenvío de reenvío.",
        attachments=[("doc.pdf", b"pdf")],
    )
    watcher = watcher_factory(messages={"70004": raw_email})

    processed = watcher._process_email("70004")

    assert processed is True
    case_dir = tmp_path / "Carlos_Ruiz"
    assert case_dir.is_dir()


def test_adjunto_jpeg_se_acepta(watcher_factory, tmp_path):
    """La extensión .jpeg debe aceptarse igual que .jpg."""
    raw_email = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Adjunto foto.",
        attachments=[("foto_titulo.jpeg", b"jpeg content")],
    )
    watcher = watcher_factory(messages={"70005": raw_email})

    processed = watcher._process_email("70005")

    case_dir = tmp_path / "Juan_Perez"
    assert processed is True
    assert (case_dir / "foto_titulo.jpeg").is_file()


def test_adjunto_con_extension_mayusculas_se_acepta(watcher_factory, tmp_path):
    """Extensiones en mayúsculas (.PDF, .JPG) deben aceptarse."""
    raw_email = build_email(
        subject="Expediente Docente - Juan Pérez",
        body="Documentos escaneados.",
        attachments=[("SCAN_001.PDF", b"pdf data"), ("FOTO.JPG", b"jpg data")],
    )
    watcher = watcher_factory(messages={"70006": raw_email})

    processed = watcher._process_email("70006")

    case_dir = tmp_path / "Juan_Perez"
    assert processed is True
    saved_files = {p.name for p in case_dir.iterdir()}
    assert "SCAN_001.PDF" in saved_files
    assert "FOTO.JPG" in saved_files


def test_state_file_formato_anterior_sin_fingerprints(tmp_path, monkeypatch):
    """Un state file con formato viejo (sin fingerprints) debe migrar correctamente."""
    monkeypatch.setenv("MAIL_USER", "watcher@example.com")
    monkeypatch.setenv("MAIL_PASS", "secret")
    monkeypatch.setenv("MAIL_HOST", "imap.example.com")

    uid_state_file = tmp_path / "uids.json"
    uid_state_file.write_text('{"uids": ["100", "200"]}', encoding="utf-8")
    monkeypatch.setattr(wa, "UID_STATE_FILE", uid_state_file, raising=False)
    monkeypatch.setattr(wa, "INPUT_DIR", tmp_path, raising=False)

    watcher = WatcherAgent()

    assert watcher.processed_uids == {"100", "200"}
    assert watcher.processed_fingerprints == set()


def test_state_file_formato_lista_legacy(tmp_path, monkeypatch):
    """Un state file con formato de lista pura debe funcionar."""
    monkeypatch.setenv("MAIL_USER", "watcher@example.com")
    monkeypatch.setenv("MAIL_PASS", "secret")
    monkeypatch.setenv("MAIL_HOST", "imap.example.com")

    uid_state_file = tmp_path / "uids.json"
    uid_state_file.write_text('["100", "200", "300"]', encoding="utf-8")
    monkeypatch.setattr(wa, "UID_STATE_FILE", uid_state_file, raising=False)
    monkeypatch.setattr(wa, "INPUT_DIR", tmp_path, raising=False)

    watcher = WatcherAgent()

    assert watcher.processed_uids == {"100", "200", "300"}
    assert watcher.processed_fingerprints == set()


def test_correo_sin_asunto(watcher_factory, tmp_path, monkeypatch):
    """Un correo sin asunto con keyword en el cuerpo debe procesarse."""
    monkeypatch.setattr(wa, "BODY_KEYWORDS", ["Certificado"])
    msg = EmailMessage()
    msg["From"] = "docente@example.com"
    msg["To"] = "watcher@example.com"
    msg.set_content("Adjunto Certificado de notas.")
    msg.add_attachment(b"pdf data", maintype="application", subtype="pdf", filename="cert.pdf")
    raw_email = msg.as_bytes()

    watcher = watcher_factory(messages={"80001": raw_email})

    processed = watcher._process_email("80001")

    assert processed is True
    folders = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(folders) == 1


def test_correo_con_cuerpo_vacio(watcher_factory, tmp_path):
    """Un correo con keyword en asunto pero cuerpo vacío debe procesarse."""
    raw_email = build_email(
        subject="Expediente Docente - María López",
        body="",
        attachments=[("doc.pdf", b"pdf")],
    )
    watcher = watcher_factory(messages={"80002": raw_email})

    processed = watcher._process_email("80002")

    case_dir = tmp_path / "Maria_Lopez"
    assert processed is True
    info = case_dir / "info_mail_Maria_Lopez.txt"
    assert info.is_file()
    assert info.read_text(encoding="utf-8") == "Correo sin contenido de texto."


def test_correo_html_only_sin_text_plain(watcher_factory, tmp_path, monkeypatch):
    """Un correo HTML-only no tiene text/plain; las body keywords no matchean."""
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", ["Consulta"])
    monkeypatch.setattr(wa, "BODY_KEYWORDS", ["Certificado"])
    msg = EmailMessage()
    msg["Subject"] = "Consulta general"
    msg["From"] = "user@example.com"
    msg["To"] = "watcher@example.com"
    msg.set_content("<html><body><p>Adjunto Certificado</p></body></html>", subtype="html")
    msg.add_attachment(b"pdf", maintype="application", subtype="pdf", filename="cert.pdf")
    raw_email = msg.as_bytes()

    watcher = watcher_factory(messages={"80003": raw_email})

    # Subject no tiene "Certificado", body es HTML (no text/plain) así que body_match falla
    # Pero "Consulta" está en SUBJECT_KEYWORDS y matchea en el asunto
    processed = watcher._process_email("80003")

    assert processed is True


def test_correo_html_only_body_keyword_no_matchea(watcher_factory, tmp_path, monkeypatch):
    """Si el email es HTML-only y la keyword solo está en el body HTML, no matchea."""
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", ["NingunaKeyword"])
    monkeypatch.setattr(wa, "BODY_KEYWORDS", ["Certificado"])
    msg = EmailMessage()
    msg["Subject"] = "Documentos adjuntos"
    msg["From"] = "user@example.com"
    msg["To"] = "watcher@example.com"
    msg.set_content("<html><body><p>Adjunto Certificado</p></body></html>", subtype="html")
    msg.add_attachment(b"pdf", maintype="application", subtype="pdf", filename="cert.pdf")
    raw_email = msg.as_bytes()

    watcher = watcher_factory(messages={"80004": raw_email})

    processed = watcher._process_email("80004")

    # Ni subject ni body (text/plain) matchean
    assert processed is False


def test_keyword_case_insensitive_en_asunto(watcher_factory, tmp_path, monkeypatch):
    """Las keywords deben matchear sin importar mayúsculas/minúsculas."""
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", ["certificado"])
    raw_email = build_email(
        subject="CERTIFICADO DE NOTAS - Juan Pérez",
        body="Adjunto.",
        attachments=[("cert.pdf", b"pdf")],
    )
    watcher = watcher_factory(messages={"80005": raw_email})

    processed = watcher._process_email("80005")

    assert processed is True


def test_keyword_case_insensitive_en_cuerpo(watcher_factory, tmp_path, monkeypatch):
    """Las body keywords matchean sin importar case."""
    monkeypatch.setattr(wa, "SUBJECT_KEYWORDS", ["NingunaKeyword"])
    monkeypatch.setattr(wa, "BODY_KEYWORDS", ["curriculum"])
    raw_email = build_email(
        subject="Documentos - Ana Torres",
        body="Adjunto mi CURRICULUM VITAE actualizado.",
        attachments=[("cv.pdf", b"pdf")],
    )
    watcher = watcher_factory(messages={"80006": raw_email})

    processed = watcher._process_email("80006")

    assert processed is True


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
