"""Watcher Agent para monitorear correos con expedientes docentes."""
import imaplib
import email
import email.message
import email.header
import re
import json
import time
import os
from pathlib import Path
from typing import Set, List, Optional, Tuple
from email.header import decode_header
from email.utils import parsedate_to_datetime

from src.core.logger import logger
from src.config import config


class WatcherAgent:
    """Agente que monitorea correos IMAP buscando expedientes docentes."""

    def __init__(self) -> None:
        """Inicializa el WatcherAgent."""
        self.processed_uids: Set[str] = set()
        self.imap_client: Optional[imaplib.IMAP4_SSL] = None
        self.SUBJECT_KEYWORD = "Expediente"
        self._load_processed_uids()

    def _load_processed_uids(self) -> None:
        """Carga los UIDs ya procesados desde el archivo JSON."""
        try:
            if os.path.exists(config.PROCESSED_UIDS_FILE):
                with open(config.PROCESSED_UIDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.processed_uids = set(data.get("uids", []))
                logger.info(f"Cargados {len(self.processed_uids)} UIDs procesados")
            else:
                logger.info("No se encontró archivo de UIDs procesados, comenzando desde cero")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error al cargar UIDs procesados: {e}. Continuando con lista vacía")

    def _save_processed_uids(self) -> None:
        """Guarda los UIDs procesados en el archivo JSON."""
        try:
            data = {"uids": list(self.processed_uids)}
            with open(config.PROCESSED_UIDS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Error al guardar UIDs procesados: {e}")

    def _connect_imap(self) -> bool:
        """Establece conexión con el servidor IMAP."""
        try:
            if config.MAIL_SSL:
                self.imap_client = imaplib.IMAP4_SSL(config.MAIL_HOST)
            else:
                self.imap_client = imaplib.IMAP4(config.MAIL_HOST)

            self.imap_client.login(config.MAIL_USER, config.MAIL_PASS)
            self.imap_client.select(config.MAIL_FOLDER)
            logger.info(f"Conectado a {config.MAIL_HOST} en carpeta {config.MAIL_FOLDER}")
            return True
        except imaplib.IMAP4.error as e:
            logger.error(f"Error de autenticación IMAP: {e}")
            return False
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"Error de conexión IMAP: {e}")
            return False
        except Exception as e:
            logger.error(f"Error inesperado al conectar IMAP: {e}")
            return False

    def _disconnect_imap(self) -> None:
        """Cierra la conexión IMAP."""
        try:
            if self.imap_client:
                self.imap_client.close()
                self.imap_client.logout()
                self.imap_client = None
                logger.debug("Desconectado de IMAP")
        except Exception as e:
            logger.warning(f"Error al desconectar IMAP: {e}")

    def _decode_header(self, header: Optional[str]) -> str:
        """Decodifica el header del correo considerando diferentes codificaciones."""
        if not header:
            return ""

        try:
            decoded_parts = decode_header(header)
            decoded_string = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        decoded_string += part.decode(encoding)
                    else:
                        # Intentar detectar la codificación
                        try:
                            decoded_string += part.decode("utf-8")
                        except UnicodeDecodeError:
                            decoded_string += part.decode("latin-1", errors="ignore")
                else:
                    decoded_string += str(part)
            return decoded_string
        except Exception as e:
            logger.warning(f"Error al decodificar header: {e}")
            return str(header) if header else ""

    def _decode_subject(self, msg: email.message.Message) -> str:
        """Decodifica el Subject del mensaje usando email.header."""
        raw = msg.get('Subject', '')
        if not raw:
            return ""
        
        try:
            parts = email.header.decode_header(raw)
            decoded = []
            for text, enc in parts:
                if isinstance(text, bytes):
                    decoded.append(text.decode(enc or 'utf-8', errors='replace'))
                else:
                    decoded.append(str(text))
            return ''.join(decoded)
        except Exception as e:
            logger.warning(f"Error al decodificar Subject: {e}")
            return str(raw) if raw else ""

    def _search_emails_with_subject(self) -> List[bytes]:
        """Busca correos cuyo asunto contenga la palabra clave usando X-GM-RAW (Gmail) o fallback estándar."""
        try:
            # Intentar primero con X-GM-RAW (Gmail) - usar search() directamente
            try:
                status, data = self.imap_client.search(None, 'X-GM-RAW', f'subject:{self.SUBJECT_KEYWORD} in:inbox')
                if status == 'OK' and data and data[0]:
                    ids = data[0].split()
                    logger.info(f"Total (X-GM-RAW) con asunto '{self.SUBJECT_KEYWORD}': {len(ids)}")
                    return ids
            except Exception as e:
                logger.warning(f"No se pudo usar X-GM-RAW: {e}")

            # Fallback estándar
            status, data = self.imap_client.search(None, 'ALL', f'SUBJECT "{self.SUBJECT_KEYWORD}"')
            ids = data[0].split() if (status == 'OK' and data and data[0]) else []
            logger.info(f"Total (SEARCH) con asunto '{self.SUBJECT_KEYWORD}': {len(ids)}")
            return ids

        except Exception as e:
            logger.error(f"Error al buscar correos: {e}")
            return []

    def _get_email_by_seq_num(self, seq_num: str) -> Tuple[Optional[email.message.Message], Optional[str]]:
        """Obtiene un correo por su número de secuencia y retorna también su UID real."""
        try:
            seq_int = int(seq_num)
            # Obtener el correo completo y su UID en una sola llamada
            status, messages = self.imap_client.fetch(str(seq_int), "(RFC822 UID)")
            if status != "OK" or not messages:
                logger.warning(f"No se pudo obtener correo con número de secuencia {seq_num}")
                return None, None

            # Extraer UID y correo de la respuesta IMAP
            # El formato típico es: (b'1 (UID 123)', b'RFC822 data...') o (b'1 (UID 123 RFC822 {1234}', b'data...')
            uid_real = None
            raw_email = None
            
            # Procesar la respuesta de IMAP
            for item in messages:
                if isinstance(item, tuple):
                    # El primer elemento contiene el número de secuencia y UID
                    if len(item) > 0 and isinstance(item[0], bytes):
                        # Buscar UID en la respuesta (formato: b'1 (UID 123)')
                        uid_match = re.search(rb'UID\s+(\d+)', item[0])
                        if uid_match:
                            uid_real = uid_match.group(1).decode('utf-8')
                    
                    # El segundo elemento contiene el correo RFC822
                    if len(item) > 1:
                        if isinstance(item[1], bytes):
                            raw_email = item[1]
                        elif isinstance(item[1], tuple) and len(item[1]) > 0:
                            # Formato alternativo: datos anidados
                            raw_email = item[1][0] if isinstance(item[1][0], bytes) else None
            
            # Si no encontramos el correo, intentar formato estándar
            if not raw_email and messages:
                # Formato estándar: (b'response', b'email data')
                if isinstance(messages[0], tuple) and len(messages[0]) > 1:
                    raw_email = messages[0][1] if isinstance(messages[0][1], bytes) else None
            
            if not raw_email:
                logger.warning(f"No se pudo extraer el correo de la respuesta para {seq_num}")
                return None, None
                
            email_message = email.message_from_bytes(raw_email)
            return email_message, uid_real
            
        except Exception as e:
            logger.error(f"Error al obtener correo con número de secuencia {seq_num}: {e}")
            return None, None

    def _save_email_body(self, email_msg: email.message.Message, output_dir: Path) -> None:
        """Guarda el cuerpo del correo en un archivo de texto."""
        try:
            body_content = []
            body_content.append(f"From: {self._decode_header(email_msg.get('From'))}\n")
            body_content.append(f"To: {self._decode_header(email_msg.get('To'))}\n")
            body_content.append(f"Subject: {self._decode_header(email_msg.get('Subject'))}\n")
            body_content.append(f"Date: {self._decode_header(email_msg.get('Date'))}\n")
            body_content.append("\n" + "=" * 80 + "\n\n")

            # Obtener el cuerpo del correo
            if email_msg.is_multipart():
                for part in email_msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                charset = part.get_content_charset() or "utf-8"
                                body_content.append(payload.decode(charset, errors="ignore"))
                        except Exception as e:
                            logger.warning(f"Error al decodificar parte del correo: {e}")
            else:
                try:
                    payload = email_msg.get_payload(decode=True)
                    if payload:
                        charset = email_msg.get_content_charset() or "utf-8"
                        body_content.append(payload.decode(charset, errors="ignore"))
                except Exception as e:
                    logger.warning(f"Error al decodificar cuerpo del correo: {e}")

            # Guardar en archivo
            info_file = output_dir / "info_mail.txt"
            with open(info_file, "w", encoding="utf-8") as f:
                f.write("".join(body_content))
            logger.debug(f"Guardado cuerpo del correo en {info_file}")

        except Exception as e:
            logger.error(f"Error al guardar cuerpo del correo: {e}")

    def _save_attachments(
        self, email_msg: email.message.Message, output_dir: Path, uid: str
    ) -> int:
        """Guarda los adjuntos PDF y DOCX del correo."""
        saved_count = 0

        try:
            if not email_msg.is_multipart():
                return saved_count

            # Contar partes MIME para logging
            parts = list(email_msg.walk())
            logger.debug(f"UID={uid} partes MIME inspeccionadas para adjuntos: {len(parts)}")

            for part in parts:
                content_disposition = str(part.get("Content-Disposition", ""))
                if "attachment" not in content_disposition.lower():
                    continue

                filename = part.get_filename()
                if not filename:
                    continue

                # Decodificar nombre del archivo
                filename = self._decode_header(filename)

                # Filtrar solo PDF y DOCX
                if not (filename.lower().endswith(".pdf") or filename.lower().endswith(".docx")):
                    logger.debug(f"Archivo {filename} omitido (no es PDF ni DOCX)")
                    continue

                try:
                    # Obtener contenido del adjunto
                    payload = part.get_payload(decode=True)
                    if not payload or len(payload) == 0:
                        logger.warning(f"Adjunto {filename} está vacío, omitiendo")
                        continue

                    # Limpiar nombre de archivo para evitar problemas con caracteres especiales
                    safe_filename = "".join(
                        c for c in filename if c.isalnum() or c in ".-_ "
                    ).strip()

                    if not safe_filename:
                        safe_filename = f"attachment_{saved_count + 1}"

                    # Añadir extensión si no tiene
                    if not safe_filename.lower().endswith((".pdf", ".docx")):
                        ext = Path(filename).suffix
                        safe_filename += ext if ext else ".pdf"

                    # Guardar archivo
                    file_path = output_dir / safe_filename
                    with open(file_path, "wb") as f:
                        f.write(payload)
                    saved_count += 1
                    logger.info(f"📎 Guardado adjunto: {safe_filename} en {file_path}")

                except Exception as e:
                    logger.error(f"Error al guardar adjunto {filename}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error al procesar adjuntos: {e}")

        return saved_count

    def _process_email(self, identifier: bytes) -> bool:
        """Procesa un correo individual usando número de secuencia o UID."""
        try:
            # Convertir identificador a string
            identifier_str = identifier.decode() if isinstance(identifier, bytes) else str(identifier)
            
            # Obtener correo y UID real
            email_msg = None
            uid_str = None
            
            try:
                # Intentar como número de secuencia (si viene de search())
                seq_num = int(identifier_str)
                email_msg, uid_str = self._get_email_by_seq_num(identifier_str)
                if not email_msg:
                    logger.warning(f"No se pudo obtener correo con número de secuencia {identifier_str}")
                    return False
                if not uid_str:
                    # Si no se pudo obtener el UID, usar el número de secuencia como fallback
                    logger.warning(f"No se pudo obtener UID real para {identifier_str}, usando número de secuencia")
                    uid_str = identifier_str
            except ValueError:
                # Ya es un UID, usar método original
                uid_str = identifier_str
                status, messages = self.imap_client.uid('FETCH', uid_str, "(RFC822)")
                if status != "OK" or not messages:
                    logger.warning(f"No se pudo obtener correo con UID {uid_str}")
                    return False
                raw_email = messages[0][1]
                email_msg = email.message_from_bytes(raw_email)
            
            # Verificar si ya fue procesado (idempotencia usando UID real)
            if uid_str in self.processed_uids:
                logger.debug(f"UID {uid_str} ya procesado, omitiendo")
                return False

            # Decodificar el Subject del lado del cliente
            subj = self._decode_subject(email_msg).strip()
            
            # Log UID + Subject
            logger.info(f"UID={uid_str} Subject='{subj}'")

            # Filtro exacto para 'Expediente Docente - ...' (case-insensitive)
            if not subj.lower().startswith("expediente docente -"):
                logger.debug(f"UID={uid_str} descartado: el asunto no comienza con 'Expediente Docente -'")
                # Marcar como procesado para no volver a revisarlo
                self.processed_uids.add(uid_str)
                self._save_processed_uids()
                return False

            # Crear directorio para este correo
            email_dir = Path(config.INPUT_DIR) / uid_str
            email_dir.mkdir(parents=True, exist_ok=True)

            # Guardar cuerpo del correo
            self._save_email_body(email_msg, email_dir)

            # Guardar adjuntos
            attachments_count = self._save_attachments(email_msg, email_dir, uid_str)

            # Marcar como procesado (usando UID real)
            self.processed_uids.add(uid_str)
            self._save_processed_uids()

            logger.success(
                f"Procesado UID {uid_str}: {attachments_count} adjunto(s) guardado(s) en {email_dir}"
            )
            return True

        except Exception as e:
            logger.error(f"Error al procesar correo: {e}")
            return False

    def _check_new_emails(self) -> int:
        """Busca y procesa todos los correos nuevos con expedientes."""
        processed_count = 0

        try:
            # Reconectar si es necesario
            if not self.imap_client:
                if not self._connect_imap():
                    return processed_count

            # Búsqueda robusta (X-GM-RAW o fallback)
            identifiers = self._search_emails_with_subject()

            # Procesar cada correo con filtro del lado del cliente
            for identifier in identifiers:
                # Procesar correo (incluye filtro de asunto y idempotencia)
                if self._process_email(identifier):
                    processed_count += 1

        except Exception as e:
            logger.error(f"Error al procesar correos: {e}")
            # Intentar reconectar en la siguiente iteración
            self._disconnect_imap()

        return processed_count

    def run(self) -> None:
        """Ejecuta el watcher en un loop infinito."""
        logger.info("Watcher Agent iniciado")
        config.validate()
        config.ensure_directories()

        try:
            while True:
                # Conectar a IMAP
                if not self._connect_imap():
                    logger.warning(
                        f"Error de conexión. Reintentando en {config.POLL_INTERVAL_SECONDS} segundos..."
                    )
                    time.sleep(int(config.POLL_INTERVAL_SECONDS))
                    continue

                # Buscar y procesar correos nuevos
                self._check_new_emails()

                # Desconectar
                self._disconnect_imap()

                # Esperar antes de la siguiente iteración
                logger.info(f"Esperando {int(config.POLL_INTERVAL_SECONDS)} segundos antes del siguiente ciclo...")
                time.sleep(int(config.POLL_INTERVAL_SECONDS))

        except KeyboardInterrupt:
            logger.info("Watcher Agent detenido por el usuario")
            self._disconnect_imap()

