from __future__ import annotations

import contextlib
import email
import hashlib
import imaplib
import json
import os
import re
import signal
import time
import unicodedata
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Set, Tuple

from dotenv import load_dotenv

from src import config
from src.core.logger import logger

load_dotenv()

_raw_subject_kw = os.getenv("SUBJECT_KEYWORD", "Expediente Docente")
SUBJECT_KEYWORDS: list[str] = [kw.strip() for kw in _raw_subject_kw.split(",") if kw.strip()]
_raw_body_kw = os.getenv("BODY_KEYWORD", "")
BODY_KEYWORDS: list[str] = [kw.strip() for kw in _raw_body_kw.split(",") if kw.strip()]
ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
}


def _normalize_text(text: str) -> str:
    """Elimina diacríticos/tildes para comparación insensible a acentos."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower()
REQUIRED_ATTACHMENT_EXTENSIONS = ATTACHMENT_EXTENSIONS
UID_STATE_FILE = config.PROCESSED_UIDS_FILE
INPUT_DIR = config.INPUT_DIR

INPUT_DIR.mkdir(parents=True, exist_ok=True)
UID_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


class WatcherAgent:
    """Agente que monitorea correos de expedientes docentes vía IMAP."""

    def __init__(self, timeout: Optional[int] = None) -> None:
        self.user = os.getenv("MAIL_USER")
        self.password = os.getenv("MAIL_PASS")
        self.host = os.getenv("MAIL_HOST")
        self.folder = os.getenv("MAIL_FOLDER", "INBOX")
        self.timeout = timeout or int(os.getenv("MAIL_TIMEOUT", "30"))
        self.poll_interval = float(
            os.getenv("POLL_INTERVAL_SECONDS", str(config.POLL_INTERVAL_SECONDS))
        )
        self.imap_client: Optional[imaplib.IMAP4_SSL] = None

        state = self._load_state()
        self.processed_uids: Set[str] = state[0]
        self.processed_fingerprints: Set[str] = state[1]

    def run(self) -> None:
        """Ejecuta el watcher en un loop infinito."""

        logger.info("Watcher Agent iniciado")
        config.validate()
        config.ensure_directories()

        def _handle_sigterm(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _handle_sigterm)

        cycle = 0

        try:
            while True:
                cycle += 1
                logger.info(f" Ciclo #{cycle} de monitoreo iniciado")

                if not self._connect_imap():
                    logger.warning(
                        f"No se pudo establecer conexión IMAP en el ciclo #{cycle}. "
                        f"Se reintentará en {int(self.poll_interval)} segundos..."
                    )
                    time.sleep(self.poll_interval)
                    continue

                processed_in_cycle = self._check_new_emails()

                logger.info(
                    f" Resumen ciclo #{cycle}: {processed_in_cycle} correo(s) procesado(s) "
                    f"en esta consulta."
                )

                self._disconnect_imap()

                logger.info(
                    f" El Watcher volverá a ejecutarse automáticamente en "
                    f"{int(self.poll_interval)} segundos..."
                )
                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info("Watcher Agent detenido por el usuario (KeyboardInterrupt)")
            self._disconnect_imap()
        except Exception as exc:  # pragma: no cover - protección runtime
            logger.exception(f"Error no controlado en el loop principal del Watcher: {exc}")
            self._disconnect_imap()

    def _check_new_emails(self) -> int:
        """Busca y procesa todos los correos nuevos con expedientes."""

        processed_count = 0

        try:
            if not self.imap_client and not self._connect_imap():
                logger.warning("No se pudo conectar a IMAP en este ciclo de consulta.")
                return processed_count

            identifiers = self._search_emails()
            total_ids = len(identifiers)

            logger.info(
                f" Inicio de consulta: se encontraron {total_ids} correo(s) candidato(s) "
                f"por asunto o palabras clave en el cuerpo."
            )

            for identifier in identifiers:
                if self._process_email(identifier):
                    processed_count += 1

            logger.info(
                f" Fin de consulta: se procesaron {processed_count} correo(s) con expediente docente "
                f"de un total de {total_ids} candidato(s)."
            )

            if processed_count:
                self._save_state()

        except Exception as exc:
            logger.error(f"Error al procesar correos en este ciclo: {exc}")
            self._disconnect_imap()

        return processed_count

    def _connect_imap(self) -> bool:
        if self.imap_client:
            return True

        try:
            connection = imaplib.IMAP4_SSL(self.host, timeout=self.timeout)
            connection.login(self.user, self.password)
            status, _ = connection.select(self.folder)
            if status != "OK":
                raise RuntimeError(f"No se pudo seleccionar la carpeta {self.folder}")
            self.imap_client = connection
            return True
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
            logger.exception(f"Error de conexión IMAP: {exc}")
            self._disconnect_imap()
            return False

    def _disconnect_imap(self) -> None:
        if not self.imap_client:
            return

        with contextlib.suppress(imaplib.IMAP4.error):
            self.imap_client.close()
        with contextlib.suppress(imaplib.IMAP4.error):
            self.imap_client.logout()

        self.imap_client = None

    @staticmethod
    def _keyword_variants(keywords: list[str]) -> list[str]:
        """Genera variantes de keywords incluyendo versiones sin acentos.

        Esto permite que keyword 'Currículum' también busque 'Curriculum'
        y viceversa en servidores IMAP que no normalicen acentos.
        """
        seen: set[str] = set()
        variants: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                variants.append(kw)
            norm = _normalize_text(kw)
            # Si la versión sin acentos es diferente, agregarla con el case original
            norm_titled = norm.title() if kw[0:1].isupper() else norm
            if norm_titled not in seen and norm_titled.lower() != kw.lower():
                seen.add(norm_titled)
                variants.append(norm_titled)
        return variants

    def _search_emails(self) -> list[str]:
        """Busca correos que coincidan por asunto o por palabras clave en el cuerpo."""
        if not self.imap_client:
            return []

        subject_kws = self._keyword_variants(SUBJECT_KEYWORDS)
        body_kws = self._keyword_variants(BODY_KEYWORDS)

        # --- Intento 1: Gmail X-GM-RAW con query combinada (asunto OR keywords) ---
        # in:inbox excluye categorías como Promociones, Social y Notificaciones
        gmail_terms: list[str] = []
        for kw in subject_kws:
            gmail_terms.append(f'subject:"{kw}"')
        for kw in body_kws:
            gmail_terms.append(f'"{kw}"')
        gmail_query = "in:inbox (" + " OR ".join(gmail_terms) + ") has:attachment"

        try:
            status, data = self.imap_client.uid(
                "SEARCH", "X-GM-RAW", gmail_query.encode("utf-8"),
            )
            if status == "OK" and data and data[0]:
                return self._parse_uid_list(data[0])
        except (imaplib.IMAP4.error, UnicodeEncodeError) as exc:
            logger.debug(f"X-GM-RAW no soportado, usando búsqueda estándar: {exc}")

        # --- Intento 2: IMAP estándar - búsqueda por asunto ---
        # Gmail IMAP no soporta CHARSET UTF-8 ni búsqueda accent-insensitive,
        # así que solo se usan keywords ASCII. Los emails con asuntos acentuados
        # se capturan por la búsqueda amplia por fecha (intento 2c) y se filtran
        # localmente con _normalize_text() en _process_email().
        all_uids: list[str] = []

        for kw in subject_kws:
            if not kw.isascii():
                continue
            try:
                status, data = self.imap_client.uid(
                    "SEARCH", None, f'(SUBJECT "{kw}")',
                )
                if status == "OK" and data and data[0]:
                    for uid_str in self._parse_uid_list(data[0]):
                        if uid_str not in all_uids:
                            all_uids.append(uid_str)
            except imaplib.IMAP4.error as exc:
                logger.debug(f"Error en búsqueda por asunto keyword '{kw}': {exc}")

        # --- Intento 2b: IMAP estándar - búsqueda por body keywords ---
        for kw in body_kws:
            if not kw.isascii():
                continue
            try:
                status, data = self.imap_client.uid(
                    "SEARCH", None, f'(BODY "{kw}")',
                )
                if status == "OK" and data and data[0]:
                    for uid_str in self._parse_uid_list(data[0]):
                        if uid_str not in all_uids:
                            all_uids.append(uid_str)
            except imaplib.IMAP4.error as exc:
                logger.debug(f"Error en búsqueda por body keyword '{kw}': {exc}")

        # --- Intento 2c: búsqueda amplia por fecha ---
        # Captura emails recientes con adjuntos que las keywords ASCII no encuentran
        # (ej: asuntos con acentos como "Currículum"). Se filtran localmente después.
        try:
            since_date = (
                __import__("datetime").datetime.now()
                - __import__("datetime").timedelta(days=7)
            ).strftime("%d-%b-%Y")
            status, data = self.imap_client.uid(
                "SEARCH", None, f'(SINCE "{since_date}")',
            )
            if status == "OK" and data and data[0]:
                for uid_str in self._parse_uid_list(data[0]):
                    if uid_str not in all_uids:
                        all_uids.append(uid_str)
        except imaplib.IMAP4.error as exc:
            logger.debug(f"Error en búsqueda amplia por fecha: {exc}")

        return all_uids

    @staticmethod
    def _parse_uid_list(raw_data: bytes) -> list[str]:
        uids: list[str] = []
        for uid in raw_data.split():
            if not isinstance(uid, (bytes, bytearray)) or not uid:
                continue
            uid_str = uid.decode("utf-8").strip()
            if uid_str and uid_str not in uids:
                uids.append(uid_str)
        return uids

    def _process_email(self, uid_str: str) -> bool:
        logger.info(f" Iniciando procesamiento para UID {uid_str}")

        if uid_str in self.processed_uids:
            logger.info(f"UID {uid_str} ya procesado previamente, se omite")
            return False

        if not self.imap_client:
            logger.warning(f"No hay conexión IMAP activa para procesar UID {uid_str}")
            return False

        try:
            status, messages = self.imap_client.uid("FETCH", uid_str, "(RFC822)")
        except imaplib.IMAP4.error as exc:
            logger.exception(f"No se pudo recuperar el correo UID {uid_str}: {exc}")
            return False

        if status != "OK" or not messages or messages[0] is None:
            logger.error(f"Respuesta inválida al descargar el correo UID {uid_str}")
            return False

        raw_email = messages[0][1]
        email_msg = email.message_from_bytes(raw_email, policy=policy.default)

        subject = self._decode_subject(email_msg)
        logger.info(f"UID={uid_str} Subject='{subject}'")

        body = self._extract_text_body(email_msg)

        fingerprint = self._compute_fingerprint(subject, body, email_msg)
        if fingerprint in self.processed_fingerprints:
            logger.info(
                f"UID {uid_str} es un duplicado por contenido (fingerprint={fingerprint[:12]}…), se omite"
            )
            self.processed_uids.add(uid_str)
            self._save_state()
            return False

        subject_match = any(
            _normalize_text(kw) in _normalize_text(subject) for kw in SUBJECT_KEYWORDS
        )
        body_match = bool(BODY_KEYWORDS) and any(
            _normalize_text(kw) in _normalize_text(body) for kw in BODY_KEYWORDS
        )

        if not subject_match and not body_match:
            logger.info(
                f"UID {uid_str} descartado: ni el asunto ni el cuerpo contienen "
                f"las palabras clave configuradas"
            )
            self.processed_uids.add(uid_str)
            self._save_state()
            return False

        if not self._has_required_attachments(email_msg):
            logger.info(
                f"UID {uid_str} descartado: no contiene adjuntos en formato "
                f"PDF o JPG requeridos"
            )
            self.processed_uids.add(uid_str)
            self._save_state()
            return False

        teacher_name = self._extract_teacher_name(subject)
        logger.info(f"Nombre extraído para UID {uid_str}: {teacher_name}")

        case_dir, safe_label = self._prepare_case_assets(teacher_name, uid_str)
        logger.info(f"Carpeta destino para UID {uid_str}: {case_dir}")

        try:
            body_path = self._write_body(case_dir, safe_label, body)
            logger.info(f"Cuerpo guardado en {body_path.name}")
        except OSError:
            logger.error(
                f"UID {uid_str} abortado: no se pudo guardar el cuerpo del correo. "
                f"Se marca como procesado para evitar reintentos infinitos."
            )
            self.processed_uids.add(uid_str)
            self._save_state()
            return False

        attachments = self._save_attachments(email_msg, case_dir)
        logger.info(f"Adjuntos guardados para UID {uid_str}: {attachments} archivo(s)")

        try:
            self.imap_client.uid("STORE", uid_str, "+FLAGS", r"(\Seen)")
        except imaplib.IMAP4.error as exc:
            logger.warning(f"No se pudo marcar como leído el UID {uid_str}: {exc}")

        self.processed_uids.add(uid_str)
        self.processed_fingerprints.add(fingerprint)
        self._save_state()

        logger.success(
            f"Procesado UID {uid_str}: {attachments} adjunto(s) guardado(s) en {case_dir}"
        )
        return True

    @staticmethod
    def _decode_subject(message: EmailMessage) -> str:
        raw_subject = message["subject"]
        if not raw_subject:
            return ""
        try:
            return str(make_header(decode_header(raw_subject)))
        except (email.errors.HeaderParseError, UnicodeDecodeError):
            logger.debug(
                f"No se pudo decodificar el asunto del correo, se usa el valor raw: {raw_subject!r}"
            )
            return str(raw_subject)

    @staticmethod
    def _extract_teacher_name(subject: str) -> Optional[str]:
        subject = subject.strip()
        if not subject:
            return None

        for kw in SUBJECT_KEYWORDS:
            primary_pattern = re.compile(
                rf"{re.escape(kw)}\s*[-–—:]\s*(.+)$",
                flags=re.IGNORECASE,
            )
            match = primary_pattern.search(subject)
            if match:
                candidate = match.group(1).strip(" -–—:\t")
                if candidate:
                    return candidate

        separators = ["-", "–", "—", ":"]
        for separator in separators:
            if separator in subject:
                candidate = subject.rsplit(separator, 1)[-1].strip()
                if len(candidate.split()) >= 2:
                    return candidate

        return None

    def _prepare_case_assets(self, teacher_name: Optional[str], uid: str) -> Tuple[Path, str]:
        safe_label = self._sanitize_fragment(teacher_name, f"UID{uid}")
        if teacher_name:
            folder_name = safe_label
        else:
            folder_name = f"Expediente_SinNombre_{safe_label}"

        case_dir = INPUT_DIR / folder_name
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir, safe_label

    def _write_body(self, case_dir: Path, safe_label: str, body: str) -> Path:
        safe_content = body.strip() or "Correo sin contenido de texto."
        target = case_dir / f"info_mail_{safe_label}.txt"
        try:
            target.write_text(safe_content, encoding="utf-8")
        except OSError as exc:
            logger.exception(f"No se pudo guardar el cuerpo del correo en {target}: {exc}")
            raise
        return target

    def _save_attachments(self, message: EmailMessage, case_dir: Path) -> int:
        saved = 0
        for attachment in message.iter_attachments():
            filename = attachment.get_filename()
            if not filename:
                continue

            extension = Path(filename).suffix.lower()
            if extension and extension not in ATTACHMENT_EXTENSIONS:
                logger.debug(f"Adjunto {filename} ignorado por extensión {extension}")
                continue

            safe_name = self._sanitize_filename(filename)
            target = self._resolve_collision(case_dir, safe_name)
            try:
                payload = attachment.get_payload(decode=True) or b""
                target.write_bytes(payload)
            except OSError as exc:
                logger.exception(f"Error guardando adjunto {target}: {exc}")
                continue

            saved += 1
        return saved

    @staticmethod
    def _has_required_attachments(message: EmailMessage) -> bool:
        """Verifica que el correo tenga al menos un adjunto PDF o JPG."""
        for attachment in message.iter_attachments():
            filename = attachment.get_filename()
            if not filename:
                continue
            extension = Path(filename).suffix.lower()
            if extension in REQUIRED_ATTACHMENT_EXTENSIONS:
                return True
        return False

    @staticmethod
    def _extract_text_body(message: EmailMessage) -> str:
        texts: list[str] = []
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_maintype() != "text":
                    continue
                if part.get_content_subtype() != "plain":
                    continue
                disposition = part.get_content_disposition()
                if disposition not in (None, "inline"):
                    continue
                try:
                    texts.append(part.get_content())
                except Exception:  # pragma: no cover - log ya controlado
                    logger.warning("No se pudo decodificar una parte del cuerpo del correo")
        else:
            if message.get_content_type() == "text/plain":
                texts.append(message.get_content())

        if texts:
            return "\n\n".join(texts).strip()
        return ""

    @staticmethod
    def _sanitize_fragment(value: Optional[str], fallback: str) -> str:
        if not value:
            return fallback

        normalized = unicodedata.normalize("NFKD", value)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_text = re.sub(r"[^\w\s-]", "", ascii_text)
        ascii_text = re.sub(r"\s+", "_", ascii_text)
        ascii_text = ascii_text.strip("_")
        return ascii_text or fallback

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        filename = os.path.basename(filename)
        normalized = unicodedata.normalize("NFKD", filename)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_text = re.sub(r"[^\w.\- ]", "_", ascii_text)
        ascii_text = ascii_text.replace(" ", "_").strip("_")
        return ascii_text or "archivo"

    @staticmethod
    def _resolve_collision(case_dir: Path, filename: str) -> Path:
        target = case_dir / filename
        counter = 1
        while target.exists():
            target = case_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
            counter += 1
        return target

    def _load_state(self) -> Tuple[Set[str], Set[str]]:
        if not UID_STATE_FILE.exists():
            return set(), set()

        try:
            content = json.loads(UID_STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("El archivo de UIDs está corrupto, se reiniciará")
            return set(), set()

        if isinstance(content, dict):
            uid_candidates = content.get("uids", [])
            fp_candidates = content.get("fingerprints", [])
        elif isinstance(content, list):
            uid_candidates = content
            fp_candidates = []
        else:
            uid_candidates = []
            fp_candidates = []

        return (
            {str(uid) for uid in uid_candidates},
            {str(fp) for fp in fp_candidates},
        )

    def _save_state(self) -> None:
        try:
            UID_STATE_FILE.write_text(
                json.dumps(
                    {
                        "uids": sorted(self.processed_uids),
                        "fingerprints": sorted(self.processed_fingerprints),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.exception(f"No se pudieron guardar los UIDs procesados: {exc}")

    @staticmethod
    def _compute_fingerprint(subject: str, body: str, message: EmailMessage) -> str:
        hasher = hashlib.sha256()
        sender = message.get("From", "") or ""
        hasher.update(sender.encode("utf-8"))
        hasher.update(subject.encode("utf-8"))
        hasher.update(body.encode("utf-8"))
        for attachment in message.iter_attachments():
            filename = attachment.get_filename() or ""
            hasher.update(filename.encode("utf-8"))
            payload = attachment.get_payload(decode=True) or b""
            hasher.update(payload)
        return hasher.hexdigest()


def run_watcher() -> None:
    watcher = WatcherAgent()
    watcher.run()


if __name__ == "__main__":
    run_watcher()

