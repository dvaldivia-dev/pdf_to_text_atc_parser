from pathlib import Path
import json
import re
import time
import traceback
import imaplib
from email import policy
from commons import build_search_criteria, load_history, save_history, already_processed, save_attachment, decode_mime_words
import email
from invoice_data import extract_headers, find_invoice_page_text, get_pdf_text_with_ocr_fallback

# ---------- DEFAULTS ----------
DEFAULT_CONFIG = {
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "username": "tu@correo.com",
    "password": "",
    "mailbox": "INBOX",
    "download_folder": str(Path.home() / "Downloads"),
    "date_start": "2025-10-01",
    "date_end": None,
    "mark_as_seen": True,
    "history_file": "processed_emails.json"
}
# --------------------------------

def load_config(path=None):
    """
    Carga configuración desde config.json (si existe). 
    path: ruta opcional al archivo JSON. Si no se pasa, busca ./config.json
    """
    cfg = DEFAULT_CONFIG.copy()
    config_path = Path(path) if path else Path("config.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            # actualizar defaults con lo que venga en el archivo
            cfg.update(user_cfg)
        except Exception as e:
            print(f"Advertencia: no se pudo leer {config_path}: {e}")
    else:
        print(f"Info: no se encontró {config_path}, usando valores por defecto.")
    return cfg

def process_mailbox(imap, cfg):
    try:
        imap.select(cfg["mailbox"])
    except imaplib.IMAP4.abort as e:
        print(f"⚠️ Error al seleccionar el buzón ({e}), reintentando conexión...")
        time.sleep(2)
        imap.noop()
        imap.select(cfg["mailbox"])

    search_query = build_search_criteria(cfg["date_start"], cfg["date_end"], cfg["search_by"])
    print(f"🔍 Buscando correos con criterio: {search_query}")

    typ, data = imap.search(None, search_query)
    if typ != "OK":
        print("❌ Error buscando correos:", typ, data)
        return

    msg_nums = data[0].split()
    print(f"📬 Correos encontrados: {len(msg_nums)}")

    history = load_history(cfg["history_file"])

    for num in msg_nums:
        downloaded_pdfs = []
        try:
            # --- 🔁 Reintento robusto de fetch ---
            for intento in range(3):
                try:
                    typ, msg_data = imap.fetch(num, "(RFC822)")
                    if typ == "OK":
                        break
                except imaplib.IMAP4.abort as e:
                    print(f"⚠️ Error IMAP ({e}), reintentando {intento + 1}/3 ...")
                    time.sleep(2)
                    imap.noop()
                    if intento == 2:
                        raise  # después de 3 intentos fallidos, abortar

            if typ != "OK":
                print(f"❌ No se pudo obtener el correo #{num}. Se omite.")
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw, policy=policy.default)

            msg_id = msg.get("Message-ID", "").strip() or f"NOID-{num.decode() if isinstance(num, bytes) else num}"

            if already_processed(history, msg_id):
                print(f"⏭️ Correo ya procesado ({msg_id}), se omite.")
                continue

            subject = decode_mime_words(msg.get("Subject", ""))
            from_ = decode_mime_words(msg.get("From", ""))
            date_ = msg.get("Date", "")

            print(f"\n📧 Procesando: {subject}")
            print(f"   De: {from_}")
            print(f"   Fecha: {date_}")

            found_any_pdf = False

            if msg.is_multipart():
                for part in msg.walk():
                    try:
                        filename = part.get_filename()
                        if not filename:
                            continue
                        filename = decode_mime_words(filename)
                        ctype = part.get_content_type()

                        if ctype == "application/pdf" or filename.lower().endswith(".pdf"):
                            payload = part.get_payload(decode=True)
                            text, pages_text = get_pdf_text_with_ocr_fallback(payload)
                            invoiceData = find_invoice_page_text(pages_text)
                            invoice_norm = re.sub(r"\r", "\n", invoiceData)
                            full_text_one = re.sub(r"[\r\n]+", " ", invoice_norm)
                            headers = extract_headers(full_text_one)

                            invoice_number = headers.get("Invoice No", "")
                            prefix = f"{invoice_number}_" if invoice_number else ""
                            new_filename = prefix + filename

                            saved_path = save_attachment(payload, new_filename, cfg["download_folder"])
                            print(f"  ✅ PDF guardado: {saved_path}")
                            downloaded_pdfs.append(new_filename)
                            found_any_pdf = True

                    except Exception as e:
                        print(f"  ❌ ERROR al procesar o guardar el PDF '{filename}': {e}")
                        traceback.print_exc()

            if not found_any_pdf:
                print("   ⚠️ No se encontraron PDFs en este correo.")

            history[msg_id] = {
                "subject": subject,
                "from": from_,
                "date": date_,
                "pdf_found": found_any_pdf,
                "downloaded_files": downloaded_pdfs
            }
            save_history(history, cfg["history_file"])

            if cfg.get("mark_as_seen"):
                imap.store(num, '+FLAGS', '\\Seen')

        except imaplib.IMAP4.abort as e:
            print(f"🚨 Error grave IMAP durante el procesamiento: {e}")
            time.sleep(3)
            try:
                imap.noop()
            except Exception:
                print("⚠️ La sesión IMAP parece haber expirado. Reconectando...")
                # reconnect_imap(imap, cfg)  # puedes implementar esta helper si quieres reconectar
        except Exception as e:
            print(f"❌ Error procesando correo: {e}")
            traceback.print_exc()