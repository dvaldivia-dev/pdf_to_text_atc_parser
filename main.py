import pytesseract
import imaplib
from pathlib import Path
from email_library import load_config, process_mailbox
from mysql_connector import get_db_connection, insert_invoice_with_connection
from pdf_library import read_pdfs_files
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def main():
    # permitir pasar ruta al config por argumento: python script.py /ruta/a/config.json
    # Ruta del archivo actual
    BASE_DIR = Path(__file__).resolve().parent
    config_path = BASE_DIR / "config.json"

    print("#######################################################################################################")
    print("Cargando configuración y conectando al correo...")
    print("#######################################################################################################")
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
    print("#######################################################################################################")
    print("Procesando correos...")
    print("#######################################################################################################")
    try:
        process_mailbox(imap, cfg)
    finally:
        try:
            imap.close()
        except:
            pass
        imap.logout()
        print("\nConexión del correo cerrada...")

    print("#######################################################################################################")
    print("Leyendo archivos descargados para extraer su información...")
    print("#######################################################################################################")

    folder_path = cfg["download_folder"]
    print(f"Iniciando procesamiento de PDFs en: {folder_path}")
    
    # 1. Obtener la lista de objetos a insertar
    invoices_to_insert = read_pdfs_files(folder_path)
    
    if not invoices_to_insert:
        print("No se encontraron nuevas facturas para insertar.")
        print("\n✅ Proceso finalizado correctamente.")
        return

    print("#######################################################################################################")
    print("Conectando con la db...")
    print("#######################################################################################################")
    # 2. Establecer la conexión a la base de datos
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"❌ ERROR: No se pudo conectar a la base de datos. {e}")
        return

    # 3. Iterar e Insertar
    print(f"\nIniciando inserción de {len(invoices_to_insert)} factura(s)...")
    with conn: # Usa 'with' para asegurar que la conexión se cierre
        for invoice in invoices_to_insert:
            result = insert_invoice_with_connection(conn, invoice)
            
            if result['status'] == 'ok':
                # Si la inserción fue exitosa, confirma los cambios.
                conn.commit()
            elif result['status'] == 'error':
                # Opcional: Si ocurre un error, puedes hacer rollback para deshacer cualquier cambio pendiente.
                conn.rollback()
                print(f"Proceso detenido o en revisión por error en factura {result['num']}.")
                
    print("\n✅ Proceso finalizado correctamente.")

main()