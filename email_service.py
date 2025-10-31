import pytesseract
import re
import time
import imaplib
from commons import build_search_criteria, load_history, save_history, already_processed, save_attachment, decode_mime_words
import email
from email import policy
import traceback
from email_library import load_config

from invoice_data import extract_headers, find_invoice_page_text, get_pdf_text_with_ocr_fallback
from read_file_information import main_orchestrator

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

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

def main():
    # permitir pasar ruta al config por argumento: python script.py /ruta/a/config.json
    config_path = r"C:\Users\obeli\Documents\admix_projects\python\pdf_reader\config.json"
    print("Cargando configuración...")
    cfg = load_config(config_path)

    if not cfg["password"]:
        print("ERROR: la contraseña viene vacía. Puedes setearla en config.json o en la variable de entorno PASSWORD.")
        return

    print("Conectando al servidor IMAP...")
    try:
        imap = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        imap.login(cfg["username"], cfg["password"])
        print("✅ Autenticado correctamente.")
    except Exception as e:
        print("Error al conectar o autenticar:", e)
        return

    try:
        process_mailbox(imap, cfg)
    finally:
        try:
            imap.close()
        except:
            pass
        imap.logout()
        print("\n✅ Finalizado. Conexión del correo cerrada.")

    print("#######################################################################################################")
    print("Leyendo archivos para extraer su información")
    print("#######################################################################################################")
    main_orchestrator(cfg["download_folder"])

main()