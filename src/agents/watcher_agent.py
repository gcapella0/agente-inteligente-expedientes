from __future__ import annotations

import contextlib
import email
import imaplib
import json
import os
import re
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

SUBJECT_TOKEN = "Expediente Docente"
ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".tif",
    ".tiff",
}
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

        self._validate_credentials()
        self.processed_uids = self._load_processed_uids()

    def _validate_credentials(self) -> None:
        missing = [
            key
            for key, value in {
                "MAIL_USER": self.user,
                "MAIL_PASS": self.password,
                "MAIL_HOST": self.host,
                "MAIL_FOLDER": self.folder,
            }.items()
            if not value
        ]
        if missing:
            raise EnvironmentError(
                f"Variables de entorno faltantes para el watcher: {', '.join(missing)}"
            )

    def run(self) -> None:
        """Ejecuta el watcher en un loop infinito."""

        logger.info("Watcher Agent iniciado")
        config.validate()
        config.ensure_directories()

        cycle = 0

        try:
            while True:
                cycle += 1
                logger.info(f"🌀 Ciclo #{cycle} de monitoreo iniciado")

                if not self._connect_imap():
                    logger.warning(
                        f"No se pudo establecer conexión IMAP en el ciclo #{cycle}. "
                        f"Se reintentará en {int(self.poll_interval)} segundos..."
                    )
                    time.sleep(self.poll_interval)
                    continue

                processed_in_cycle = self._check_new_emails()

                logger.info(
                    f"📊 Resumen ciclo #{cycle}: {processed_in_cycle} correo(s) procesado(s) "
                    f"en esta consulta."
                )

                self._disconnect_imap()

                logger.info(
                    f"⏱ El Watcher volverá a ejecutarse automáticamente en "
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

            identifiers = self._search_emails_with_subject()
            total_ids = len(identifiers)

            logger.info(
                f"🔍 Inicio de consulta: se encontraron {total_ids} correo(s) candidato(s) "
                f"con asunto '{SUBJECT_TOKEN}'."
            )

            for identifier in identifiers:
                if self._process_email(identifier):
                    processed_count += 1

            logger.info(
                f"✅ Fin de consulta: se procesaron {processed_count} correo(s) con expediente docente "
                f"de un total de {total_ids} candidato(s)."
            )

            if processed_count:
                self._save_processed_uids()

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

    def _search_emails_with_subject(self) -> list[str]:
        if not self.imap_client:
            return []

        queries = [
            ("X-GM-RAW", f'subject:"{SUBJECT_TOKEN}"'),
            (None, f'(SUBJECT "{SUBJECT_TOKEN}")'),
        ]

        for charset, query in queries:
            try:
                if charset:
                    status, data = self.imap_client.uid("SEARCH", charset, query)
                else:
                    status, data = self.imap_client.uid("SEARCH", None, query)
            except imaplib.IMAP4.error as exc:
                logger.debug(f"Error ejecutando búsqueda {query}: {exc}")
                continue

            if status != "OK":
                continue

            raw_uids = data[0] if data else b""
            if not raw_uids:
                continue

            uids: list[str] = []
            for uid in raw_uids.split():
                if not isinstance(uid, (bytes, bytearray)) or not uid:
                    continue
                uid_str = uid.decode("utf-8").strip()
                if uid_str and uid_str not in uids:
                    uids.append(uid_str)

            if uids:
                return uids

        return []

    def _process_email(self, uid_str: str) -> bool:
        logger.info(f"🚚 Iniciando procesamiento para UID {uid_str}")

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

        normalized_subject = subject.lower()
        if "expediente docente" not in normalized_subject:
            logger.info(
                f"UID {uid_str} descartado: el asunto '{subject}' no contiene la frase objetivo"
            )
            self.processed_uids.add(uid_str)
            self._save_processed_uids()
            return False

        teacher_name = self._extract_teacher_name(subject)
        logger.info(f"Nombre extraído para UID {uid_str}: {teacher_name}")
        case_dir, safe_label = self._prepare_case_assets(teacher_name, uid_str)
        logger.info(f"Carpeta destino para UID {uid_str}: {case_dir}")

        body = self._extract_text_body(email_msg)
        body_path = self._write_body(case_dir, safe_label, body)
        logger.info(f"Cuerpo guardado en {body_path.name}")

        attachments = self._save_attachments(email_msg, case_dir)
        logger.info(f"Adjuntos guardados para UID {uid_str}: {attachments} archivo(s)")

        try:
            self.imap_client.uid("STORE", uid_str, "+FLAGS", r"(\Seen)")
        except imaplib.IMAP4.error as exc:
            logger.warning(f"No se pudo marcar como leído el UID {uid_str}: {exc}")

        self.processed_uids.add(uid_str)
        self._save_processed_uids()

        logger.success(
            f"Procesado UID {uid_str}: {attachments} adjunto(s) guardado(s) en {case_dir}"
        )
        return True

    def _fetch_message(self, uid: str) -> EmailMessage:
        if not self.imap_client:
            raise RuntimeError("No hay conexión IMAP activa")

        status, data = self.imap_client.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not data or data[0] is None:
            raise RuntimeError(f"No se pudo descargar el correo UID {uid}")

        raw_email = data[0][1]
        return email.message_from_bytes(raw_email, policy=policy.default)

    @staticmethod
    def _decode_subject(message: EmailMessage) -> str:
        raw_subject = message["subject"]
        if not raw_subject:
            return ""
        try:
            return str(make_header(decode_header(raw_subject)))
        except (email.errors.HeaderParseError, UnicodeDecodeError):
            return str(raw_subject)

    @staticmethod
    def _extract_teacher_name(subject: str) -> Optional[str]:
        subject = subject.strip()
        if not subject:
            return None

        primary_pattern = re.compile(
            rf"{re.escape(SUBJECT_TOKEN)}\s*[-–—:]\s*(.+)$",
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

    def _load_processed_uids(self) -> Set[str]:
        if not UID_STATE_FILE.exists():
            return set()

        try:
            content = json.loads(UID_STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("El archivo de UIDs está corrupto, se reiniciará")
            return set()

        if isinstance(content, dict):
            candidates = content.get("uids", [])
        elif isinstance(content, list):
            candidates = content
        else:
            candidates = []

        return {str(uid) for uid in candidates}

    def _save_processed_uids(self) -> None:
        try:
            UID_STATE_FILE.write_text(
                json.dumps({"uids": sorted(self.processed_uids)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.exception(f"No se pudieron guardar los UIDs procesados: {exc}")


def run_watcher() -> None:
    watcher = WatcherAgent()
    watcher.run()


if __name__ == "__main__":
    run_watcher()

