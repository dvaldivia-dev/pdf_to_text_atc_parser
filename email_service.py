import json
import pytesseract
import os
import sys
import re
import imaplib
from commons import build_search_criteria, load_history, save_history, already_processed, save_attachment, decode_mime_words
import email
from email import policy
import traceback
from email_library import load_config

from invoice_data import extract_headers, find_invoice_page_text, get_pdf_text_with_ocr_fallback_v1
from read_file_information import read_pdfs_files

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"



def process_mailbox(imap, cfg):
    imap.select(cfg["mailbox"])
    search_query = build_search_criteria(cfg["date_start"], cfg["date_end"],cfg["search_by"] )
    print(f"Buscando correos con criterio: {search_query}")
    typ, data = imap.search(None, search_query)
    if typ != "OK":
        print("Error buscando correos:", typ, data)
        return

    msg_nums = data[0].split()
    print(f"Correos encontrados: {len(msg_nums)}")

    history = load_history(cfg["history_file"])

    for num in msg_nums:
        downloaded_pdfs = []
        try:
            typ, msg_data = imap.fetch(num, "(RFC822)")
            if typ != "OK":
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw, policy=policy.default)

            msg_id = msg.get("Message-ID", "").strip()
            if not msg_id:
                msg_id = f"NOID-{num.decode() if isinstance(num, bytes) else num}"

            if already_processed(history, msg_id):
                print(f"⏭️  Correo ya procesado ({msg_id}), se omite.")
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
                            
                            # Lógica que puede fallar (lectura, OCR, extracción de headers)
                            text, pages_text = get_pdf_text_with_ocr_fallback_v1(payload)
                            invoiceData = find_invoice_page_text(pages_text)
                            invoice_norm = re.sub(r"\r", "\n", invoiceData)
                            full_text_one = re.sub(r"[\r\n]+", " ", invoice_norm)
                            headers = extract_headers(full_text_one)
                            
                            # Lógica de nomenclatura (ya ajustada)
                            invoice_number = headers.get("Invoice No", "")
                            
                            if invoice_number:
                                prefix = invoice_number + "_"
                            else:
                                prefix = ""
                                
                            new_filename = prefix + filename
                            
                            # Guardado
                            saved_path = save_attachment(payload, new_filename, cfg["download_folder"])
                            print(f"  ✅ PDF guardado: {saved_path}")
                            downloaded_pdfs.append(new_filename)
                            found_any_pdf = True

                    except Exception as e:
                        # Si este PDF falla, imprimimos el error y el bucle continúa
                        # con el siguiente 'part' (otro adjunto) del mismo correo.
                        print(f"  ❌ ERROR al procesar o guardar el PDF '{filename}': {e}. Se omite este adjunto.")
                        # Opcional: traceback.print_exc() si necesitas el stack trace completo aquí.

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

        except Exception as e:
            print("❌ Error procesando correo:", e)
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
    read_pdfs_files(cfg["download_folder"])

main()