import os
import re
from xhtml2pdf import pisa
from string import Template 
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

# --------------------------- CREAR PDF CON HTML -------------------------------------
# Obtiene la ruta base del script (ruta de la carpeta actual)
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 

def link_callback(uri, rel):
    """
    Convierte rutas relativas (como 'style.css') en rutas absolutas del sistema de archivos.
    """
    # Construye la ruta al archivo estático
    path = os.path.join(BASE_DIR, uri.replace("/", os.path.sep))
    
    # Verifica si el archivo existe
    if os.path.isfile(path):
        return path
    
    # Devuelve la URI original si no se encuentra
    return uri 

def crear_pdf_factura_desde_archivo(nombre_archivo_pdf: str, invoice_data: dict, template_path: str) -> bool:
    """
    Genera un PDF leyendo una plantilla HTML externa ($placeholders) usando string.Template.
    """
    try:
        # 1. Leer la plantilla HTML
        with open(template_path, 'r', encoding='utf-8') as f:
            template = Template(f.read()) 

        # 2. Generar las filas de la tabla de productos (HTML)
        product_rows_html = ""
        for item in invoice_data.get('Product Details', []):
            qty = item.get('Item Qty', '0').replace('\n', ' ')
            price = item.get('Price Each', '0').replace('\n', ' ')
            amount = item.get('Amount', '0').replace('\n', ' ')
            
            # Nota: Los f-strings dentro de esta sección SÍ usan llaves {} y funcionan bien aquí.
            product_rows_html += f"""
            <tr>
                <td>{item.get('Product No.', 'N/D')}</td>
                <td>{item.get('Description', 'N/D')}</td>
                <td class="align-right">{qty} {item.get('U/M', '')}</td>
                <td class="align-right">{price}</td>
                <td class="align-right">{amount}</td>
            </tr>
            """

        # 3. Preparar el diccionario de reemplazos (Asegurarse de que no haya espacios en las claves)
        data_final = {}
        for k, v in invoice_data.items():
             # Reemplaza espacios por guiones bajos para string.Template
             data_final[k.replace(' ', '_')] = v

        # Limpieza de multilínea para Bill To/Ship To
        data_final['Bill_To'] = invoice_data.get('Bill To', 'N/D').replace('\n', '<br>')
        data_final['Ship_To'] = invoice_data.get('Ship To', 'N/D').replace('\n', '<br>')
        
        # Obtener U/M
        first_product = invoice_data.get('Product Details', [{}])
        um = first_product[0].get('U/M', 'N/D') if first_product and first_product[0] else 'N/D'
        
        # Agregamos los elementos generados
        data_final['Product_U/M'] = um
        data_final['Product_Rows'] = product_rows_html
        
        # 4. Formatear la plantilla (USANDO STRING.TEMPLATE)
        # Reemplaza $Placeholders con los valores del diccionario
        print(data_final)
        final_html = template.safe_substitute(data_final) 

        # 5. Limpiar el HTML formateado (para prevenir errores de parseo sutiles)
        final_html_clean = re.sub(r'\s+', ' ', final_html).strip()
        
        # 6. Convertir el HTML a PDF
        with open(nombre_archivo_pdf, "w+b") as result_file:
            pisa_status = pisa.CreatePDF(
                final_html_clean, 
                dest=result_file,
                # Usa la función para encontrar el archivo style.css
                link_callback=link_callback 
            )

        if pisa_status.err:
            print(f"❌ Error al crear el PDF con xhtml2pdf: {pisa_status.err}")
            return False
        
        print(f"✅ PDF '{nombre_archivo_pdf}' creado con éxito.")
        return True

    except Exception as e:
        print(f"❌ Error general al crear el PDF: {e}")
        return False


# --------------------------- FUNCIÓN PRINCIPAL ----------------------------------------

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

        # print(f"{indice}| Ship Date: {invoice['Ship Date']} | Due Date: {invoice['Due Date']} | {invoice['File']}")
        print(f"{indice}| Procesando: Invoice No: {invoice['Invoice No']} | Invoice Date: {invoice['Invoice Date']} | {invoice['File']}")
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
