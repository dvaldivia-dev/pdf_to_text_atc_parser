from pypdf import PdfReader, PdfWriter
import pytesseract
import os
import re
import shutil
import json
import hashlib
from commons import get_pdf_paths
from invoice_data import extract_invoice_data
from invoice_data import find_invoice_page_index, get_pdf_text_with_ocr_fallback
from mysql_connector import get_db_connection, insert_invoice_with_connection

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def normalize_invoice(invoice):
    def normalize_value(v):
        if isinstance(v, str):
            v = re.sub(r'\s+', ' ', v.strip())  # quita espacios y saltos de línea extra
        elif isinstance(v, list):
            return [normalize_value(i) for i in v]
        elif isinstance(v, dict):
            return {k: normalize_value(vv) for k, vv in v.items()}
        return v

    return normalize_value(invoice)

def remove_invoice_page(pdf_path, output_path):
    """
    Crea una copia del PDF sin la página que contiene los datos del invoice.
    Usa OCR si es necesario.
    """
    _, pages_text_list = get_pdf_text_with_ocr_fallback(pdf_path)

    if not pages_text_list:
        print(f"⚠️ No se pudo extraer texto del PDF: {pdf_path}")
        shutil.copy2(pdf_path, output_path)
        return

    # Detectar índice de la página del invoice
    invoice_page_index = find_invoice_page_index(pages_text_list)

    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if i != invoice_page_index:  # omitimos la página de factura
            writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)

def load_processed_pdfs(file_path="processed_pdfs.json"):
    """Carga la lista de PDFs procesados desde un archivo JSON."""
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_processed_pdfs(processed_set, file_path="processed_pdfs.json"):
    """Guarda la lista de PDFs procesados en un archivo JSON."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(list(processed_set), f, indent=2)

def read_pdfs_files(folder_pdfs):
    paths = get_pdf_paths(folder_pdfs)

    ######################### PATHS ########################
    originPathPDF = os.path.join(folder_pdfs, "origin")
    attachmentsPathPDF = os.path.join(folder_pdfs, "attachment")

    # Crear las carpetas si no existen
    os.makedirs(originPathPDF, exist_ok=True)
    os.makedirs(attachmentsPathPDF, exist_ok=True)

    completos = 0
    incompletos = 0
    lista_objetos = []
    # ✅ Cargar PDFs ya procesados previamente
    processed_hashes = load_processed_pdfs()
    print(f"Numero de archivos encontrados: {len(paths)}")
    for indice, info_pdf in enumerate(paths[:len(paths)]):
        pdf_path = info_pdf['ruta']
        pdf_filename = os.path.basename(pdf_path)

        invoice = extract_invoice_data(pdf_path)
        invoice = normalize_invoice(invoice)
        completos += 1

        clave_unica = json.dumps({
            'Invoice No': invoice.get('Invoice No'),
            'Invoice Date': invoice.get('Invoice Date'),
            'S/O#': invoice.get('S/O#'),
            'Incotenn': invoice.get('Incotenn'),
            'Payment Terms': invoice.get('Payment Terms'),
            'Ship Date': invoice.get('Ship Date'),
            'Due Date': invoice.get('Due Date'),
            'Method of Shipment': invoice.get('Method of Shipment'),
            'Subtotal': invoice.get('Subtotal'),
            'Total': invoice.get('Total'),
        }, sort_keys=True)

        
        hash_obj = hashlib.sha256(clave_unica.encode()).hexdigest()

        if hash_obj in processed_hashes:
            incompletos += 1
            continue

        print(f"{indice}| Ship Date: {invoice['Ship Date']} | Due Date: {invoice['Due Date']} | {invoice['File']}")
         # Agregamos al conjunto de únicos      
        processed_hashes.add(hash_obj)
        
        destino_origin = os.path.join(originPathPDF, pdf_filename)
        destino_attachment = os.path.join(attachmentsPathPDF, pdf_filename)

        # Agregamos la ruta al objeto
        invoice['originPath'] = destino_origin
        invoice['attachmentPath'] = destino_attachment
        es_arrow_ship_to = 1 if invoice['Ship To'].lower().startswith("arrow") else 0
        invoice['needs_review'] = es_arrow_ship_to

        ## print(invoice)
        lista_objetos.append(invoice)

        ##Mover el original a origin
        shutil.move(pdf_path, destino_origin)
        remove_invoice_page(destino_origin, destino_attachment)
    
    # ✅ Guardar el registro actualizado
    save_processed_pdfs(processed_hashes)
    return lista_objetos

def main_orchestrator(folder_path):
    """
    Orquesta la lectura de PDFs y la inserción de datos en la base de datos.
    """
    print(f"Iniciando procesamiento de PDFs en: {folder_path}")
    
    # 1. Obtener la lista de objetos a insertar
    invoices_to_insert = read_pdfs_files(folder_path)
    
    if not invoices_to_insert:
        print("No se encontraron nuevas facturas para insertar.")
        return

    # 2. Establecer la conexión a la base de datos (¡REEMPLAZA ESTO CON TUS DATOS!)
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
                
    print("\nProceso de inserción finalizado.")

# folder_pdfs = r"C:\Users\obeli\Documents\admix_projects\python\pdf_reader\pdfs\no-process"
folder_pdfs = r"D:\arrow_trading_downloaded_pdfs"
main_orchestrator(folder_pdfs)
