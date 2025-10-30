
import os
import re
from xhtml2pdf import pisa
from string import Template 

# --- CONFIGURACIÓN DE RUTAS ---
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

# --- FUNCIÓN PRINCIPAL ---

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
# Ejemplo de uso
invoice_data = {
    'Invoice No': '41494J', 
    'Invoice Date': '1/23/25', 
    'S/O#': 'P51A601', 
    'Ship To': '...', 
    'Bill To': '...', 
    'Subtotal': '111291.25', 
    'Total': '111291.25',
    'Incotenn': 'DAP: LEON, GTO', 
    'Payment Terms': 'Net 60 Days', 
    'Ship Date': '1/23/25', 
    'Due Date': '3/24/25', 
    'Method of Shipment': 'RAILCAR',
    'Product Details': [
        {'Product No.': '5102KR', 'Item Qty': '193,550', 'U/M': 'LBS', 'Description': 'Polypropylene', 'Price Each': '0.57500', 'Amount': '111,291.25'}
    ]
}

TEMPLATE_FILE = 'invoice_design.html'

crear_pdf_factura_desde_archivo(
    f"Factura_{invoice_data['Invoice No']}_Final.pdf", 
    invoice_data, 
    TEMPLATE_FILE
)