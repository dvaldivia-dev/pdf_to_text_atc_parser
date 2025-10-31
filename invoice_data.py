import os
import cv2
import numpy as np
import re
from re import I, DOTALL
import pdfplumber
import pdfplumber
from pdf2image import convert_from_path
import pytesseract
import tempfile
import io

# Se asume que pdfplumber, convert_from_path, y pytesseract están importados.
# Estas funciones se mantienen como referencia, pero la implementación
# se enfocará en la nueva estructura de retorno.

# convertir una imagen a texto
def extraer_texto_ocr(pdf_path, page_number=1):
    """
    Convierte la primera página de un PDF en texto mediante OCR.
    Usa preprocesamiento con OpenCV para mejorar la precisión.
    """
    # ✅ No necesitamos poppler_path porque ya está en el PATH del sistema
    imagenes = convert_from_path(pdf_path, dpi=300, first_page=page_number, last_page=page_number)

    # Tomar la primera página
    imagen_pil = imagenes[0]

    # Convertir a formato OpenCV
    imagen_cv = cv2.cvtColor(np.array(imagen_pil), cv2.COLOR_RGB2BGR)

    # Escala de grises + filtro de ruido
    gris = cv2.cvtColor(imagen_cv, cv2.COLOR_BGR2GRAY)
    gris = cv2.medianBlur(gris, 3)

    # Binarizar (blanco y negro puro)
    _, binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # binaria = cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

    # (Opcional) guardar para verificar visualmente
    if page_number == 1:
        cv2.imwrite("debug_imagen.png", binaria)

    # OCR con configuración flexible para texto multicolumna
    config = "--psm 4"
    texto = pytesseract.image_to_string(binaria, lang='eng', config=config)

    # Guardar el texto detectado (para depuración)
    # with open("texto_ocr.txt", "w", encoding="utf-8") as f:
    #     f.write(texto)

    return texto

# de las hojas extraidas y convertidas a texto cual es la que tiene la informacion de la factura.
def find_invoice_page_text(pages_text_list):
    """
    Busca en la lista de páginas la única que contenga los indicadores clave 
    de una factura (Invoice No/Date Y Ship To/Bill To).
    
    Args:
        pages_text_list (list): Lista de strings, donde cada string es el texto de una página.

    Returns:
        str: El texto de la página identificada como la principal de la factura.
    """
    # Indicadores de que es la página principal de la factura
    # Debe tener el encabezado (Invoice No o Invoice Date)
    invoice_indicators = re.compile(r"(Invoice\s*No|Invoice\s*Date)", re.I)
    # Y debe tener las direcciones
    address_indicators = re.compile(r"(Ship\s*To|Bill\s*To)", re.I)

    for text in pages_text_list:
        # Normalizamos el texto de la página a una sola línea para que la búsqueda sea robusta
        text_one_line = re.sub(r'[\r\n]+', ' ', text)
        
        # Condición: La página DEBE contener ambos conjuntos de indicadores
        if invoice_indicators.search(text_one_line) and address_indicators.search(text_one_line):
            # ¡Página de la factura encontrada!
            return text
    
    # Fallback: Si ninguna página cumple la condición, devolvemos la primera como mejor suposición.
    if pages_text_list:
        # print("⚠️ No se identificó la página de la factura con claridad. Usando la primera página.")
        return pages_text_list[0]
        
    return ""

def find_invoice_page_index(pages_text_list):
    """
    Devuelve el índice de la página más probable que contenga los datos principales del invoice.
    Usa un sistema de puntuación basado en indicadores.
    """

    if not pages_text_list:
        return None

    invoice_keywords = [
        "invoice no", "invoice date", "invoice#", "inv no", "inv date"
    ]
    address_keywords = [
        "ship to", "bill to", "consignee", "customer", "sold to"
    ]
    financial_keywords = [
        "subtotal", "total", "payment terms", "due date", "method of shipment", "incoterm"
    ]

    best_score = 0
    best_index = None

    for i, text in enumerate(pages_text_list):
        text_lower = text.lower().replace("\n", " ")
        score = 0

        # Suma puntos según palabras clave encontradas
        score += sum(1 for k in invoice_keywords if k in text_lower)
        score += sum(1 for k in address_keywords if k in text_lower)
        score += sum(1 for k in financial_keywords if k in text_lower)

        # Bonus si hay tanto invoice como address info
        if any(k in text_lower for k in invoice_keywords) and any(k in text_lower for k in address_keywords):
            score += 2

        if score > best_score:
            best_score = score
            best_index = i

    # Si nada fue detectado, usa la primera página como fallback
    return best_index if best_index is not None else 0

def get_pdf_text_with_ocr_fallback(pdf_source, min_text_length=50, max_pages_to_read=None):
    """
    Intenta extraer texto de un PDF (ruta de archivo o bytes) usando pdfplumber. 
    Si el texto de una página es insuficiente, recurre a OCR SÓLO para esa página.
    
    :param pdf_source: Ruta del archivo (str) O contenido del PDF en bytes (bytes).
    
    Returns:
        tuple: (full_text, pages_text_list). 
             full_text es todo el texto.
             pages_text_list es una lista con el texto de cada página.
    """
    pages_text_list = []
    temp_file_path = None # Variable para guardar la ruta temporal del archivo
    
    # 1. Determinar si es bytes o ruta, y preparar pdfplumber y la ruta para OCR
    try:
        if isinstance(pdf_source, bytes):
            # Es bytes: Creamos un archivo temporal para que las funciones basadas en ruta funcionen.
            # Nota: Si el OCR (extraer_texto_ocr) pudiera aceptar bytes, ¡sería mejor!
            # Creamos el archivo temporal en un contexto 'with' para asegurar su cierre.
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            temp_file.write(pdf_source)
            temp_file.close()
            temp_file_path = temp_file.name
            
            # Preparamos el stream de bytes para pdfplumber
            pdf_plumber_source = io.BytesIO(pdf_source)
            pdf_path_for_ocr = temp_file_path
            
        elif isinstance(pdf_source, str):
            # Es una ruta: Usamos la ruta directamente para pdfplumber y OCR.
            pdf_plumber_source = pdf_source
            pdf_path_for_ocr = pdf_source
            
        else:
            raise TypeError("pdf_source debe ser str (ruta) o bytes (contenido del PDF).")
            
    except Exception as e:
        print(f"❌ Error al preparar la fuente del PDF: {e}")
        return "", []

    try:
        # 2. Abre el PDF con pdfplumber (desde la ruta o el stream de bytes)
        with pdfplumber.open(pdf_plumber_source) as pdf:
            
            num_pages = len(pdf.pages)
            pages_to_read = num_pages if max_pages_to_read is None else min(max_pages_to_read, num_pages)
            
            for i in range(pages_to_read):
                page_num = i + 1
                page = pdf.pages[i]
                
                # --- Intento 1: Extracción de texto plano (pdfplumber) ---
                page_content = page.extract_text() or ""
                
                if len(page_content.strip()) < min_text_length:
                    # print(f"Página {page_num}: Texto plano insuficiente. Recurriendo a OCR...")
                    # --- Intento 2: OCR solo en esta página usando la ruta temporal ---
                    # USAMOS la ruta del archivo (original o temporal) para el OCR
                    # print("ruta" + pdf_path_for_ocr )
                    ocr_content = extraer_texto_ocr(pdf_path_for_ocr, page_num)
                    
                    # Si el OCR proporciona un texto significativamente mejor
                    if len(ocr_content.strip()) > len(page_content.strip()):
                        page_content = ocr_content
                        # print(f"Página {page_num}: Éxito con OCR.")
                    # else:
                        # print(f"Página {page_num}: El OCR no mejoró el resultado o fue nulo.")

                if page_content:
                    pages_text_list.append(page_content)
                
            full_text = "\n".join(pages_text_list)
            return full_text, pages_text_list
            
    except Exception as e:
        print(f"❌ Error crítico al procesar el PDF: {e}")
        return "", []
        
    finally:
        # 3. Limpieza: Eliminar el archivo temporal si fue creado
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                # print(f"Archivo temporal eliminado: {temp_file_path}")
            except OSError as e:
                print(f"Advertencia: No se pudo eliminar el archivo temporal {temp_file_path}: {e}")

# PASO 1
def extract_headers(text):
    # corregimos S/0# -> S/O#
    text = text.replace("S/0#", "S/O#")
    # patrones básicos
    m_inv = re.search(r"Invoice\s*No[:\s]*([A-Za-z0-9\-]+)", text, re.I)
    if m_inv:
        invoiceNumber = m_inv.group(1).strip()

    m_invdate = re.search(r"Invoice\s*Date[:\s]*([\d\-/\s]+)", text, re.I)
    if m_invdate:
        invoiceDate = re.sub(r"\s+", "", m_invdate.group(1).strip())

    m_so = re.search(r"(?:S/O#|S/O\s*NO)\s*[:\s]*([A-Za-z0-9\-]+)", text, re.I)
    if m_so:
        invoiceSO = m_so.group(1).strip()
    
    return {
        "Invoice No": invoiceNumber,
        "Invoice Date": invoiceDate,
        "S/O#": invoiceSO
    }

# Obtiene el valor de el pedimento buscando en todas las hojas el pdf. El S/O# puede ser erroneo, por es se busca como opcion en todas las hojas.
def extract_so_no(text):
    # La regex busca "S/O NO", seguida de ":", luego opcionalmente espacios,
    # y finalmente captura cualquier carácter (dígitos, letras, etc.) hasta
    # encontrar un espacio o un fin de línea.
    # El 're.I' (IGNORECASE) es opcional aquí pero buena práctica.
    
    # Explicación de la regex:
    # S/O\s*NO\s*:\s* -> Coincide con 'S/O NO' y el ':' (permite espacios entre y después)
    # (.*?)            -> Grupo de captura: captura *cualquier* carácter (.*),
    #                     pero de forma no codiciosa (?), es decir, hasta el primer
    #                     fin de línea o nuevo separador.
    # La expresión más específica es:
    so_no_match = re.search(r"S/O\s*NO\s*:\s*([A-Z0-9]+)", text, re.I)

    results = {}
    
    if so_no_match:
        # Capturamos y limpiamos el valor
        so_no_str = so_no_match.group(1).strip()
        results["S/O NO"] = so_no_str
    else:
        # Intentar una segunda opción si el formato es diferente (como S/O#)
        so_no_match_alt = re.search(r"S/O#\s*([A-Z0-9]+)", text, re.I)
        if so_no_match_alt:
            so_no_str = so_no_match_alt.group(1).strip()
            results["S/O NO"] = so_no_str
        else:
            results["S/O NO"] = None
    
    return results

#PASO 2
# Constantes (se asume que I y DOTALL son re.IGNORECASE y re.DOTALL respectivamente)
I = re.IGNORECASE
DOTALL = re.DOTALL

# Direcciones
PLASTICOS_BAJIO_MEXICO_ADDRESS = "Km 19.5, Carretera Panamericana, S/N\nParque Industrial El Bajío\nCuerámaro, GTO 36960 MEXICO"
REYMA_MEXICO_ADDRESS = "Calzada Industrial de la Manufactura No. 35\nParque Industrial Nogales, SO 84094 MEXICO"
REYMA_US_SHIPTO_ADDRESS = "c/o BDP International\n801 Hanover Drive\nGrapevine, TX 76051"
ARROW_MAGNOLIA_ADDRESS = "28789 Hardin Store Rd. Suite 230\nMagnolia, TX 77394"
ARROW_MAGNOLIA_ALT = "28789 Hardin Store Rd. Suite 230\nMagnolia, TX 77354"
EAGLE_PASS_ADDRESS = "c/o Villarreal & Medina Forwarding Inc.\n14404 Investment Ave.\nEagle Pass, TX 78852"
LAREDO_ADDRESS = "c/o Medina Logistic Services, Inc.\n14402 Investment Ave.\nLaredo, TX 78045"

def extract_shipto_billto(text):
    # --- Limpieza agresiva ---
    def aggressive_cleanup(t):
        t = re.sub(r'[\r\n]', ' ', t)
        t = re.sub(r'\s{2,}', ' ', t)
        t = re.sub(r'[^a-zA-Z0-9\s\,\.\/\:\-\&\n]+', '', t) # Mantener saltos de línea para BillTo
        t = re.sub(r'(BOP|BDP)\s*Internat(ional|emational)', 'BDP International', t, flags=I)
        t = re.sub(r'clo\s*BDP', 'c/o BDP', t, flags=I)
        t = re.sub(r'c o BDP', 'c/o BDP', t, flags=I)
        t = re.sub(r'ArrowTrading', 'Arrow Trading', t, flags=I)
        t = re.sub(r'Villarreal\s*&\s*Medina\s*Forwarding\s*Inc', 'Villarreal & Medina Forwarding Inc', t, flags=I)
        t = re.sub(r'Polietiienos', 'Polietilenos', t, flags=I)
        t = re.sub(r'Termofilm\s*Y\s*Espumados\s*Leon\s*SA\s*de\s*CV', 'Termofilm Y Espumados Leon SA de CV', t, flags=I)
        return t.strip()
    
    text_with_newlines = re.sub(r'\s*([a-z])\s*(c/o|R\s*F\s*C|Incoterm)', r'\1\n\2', text, flags=I)
    text = aggressive_cleanup(text_with_newlines)
    text = re.sub(r'Adherib\s+les', 'Adheribles', text, flags=re.I)
    text = re.sub(r'Plasticos?\s+Adheribles?', 'Plasticos Adheribles', text, flags=re.I)

    # --- Patrones base ---
    mexican_name_pattern = (
    r"(Pl[aá]stic\s*os?\s*Adherib?\s*les?\s*del\s*Baj[ií]o|"
    r"Grupo\s*Industrial\s*Reyma|"
    r"Polietilenos?\s*del\s*Centro|"
    r"Reyma\s*Del\s*Noroeste|"
    r"Polietilenos?\s*Del\s*Centro|"
    r"Termofilm\s*Y\s*Espumados\s*Leon)" # <--- ¡AGREGADO!
    )

    arrow_pattern = r"Arrow\s*Trading\s*LLC"
    villarreal_pattern = r"Villarreal\s*&\s*Medina\s*Forwarding\s*Inc"
    bdp_pattern = r"(c/o\s*BDP|BDP\s*International|c/o\s*BOP|BOP\s*International)"
    medina_pattern = r"Medina\s*Logistic\s*Services"

    # --- Extraer bloques ---
    shipto_block = re.search(r'Ship To:\s*(.*?)\s*Bill To:', text, flags=I | DOTALL)
    shipto_text = shipto_block.group(1).strip() if shipto_block else ""
    billto_block = re.search(r'Bill To:\s*(.*?)(RFC:|Incoterm|Payment|Subtotal|TOTAL|Product No\.|$)', text, flags=I | DOTALL)
    billto_text = billto_block.group(1).strip() if billto_block else ""

    # Si ShipTo: está vacío y BillTo tiene contenido (maneja tu caso de mezcla)
    if not shipto_text and billto_text:
        match_mexican_in_billto = re.search(mexican_name_pattern, billto_text, flags=I)
        if match_mexican_in_billto:
            shipto_text = billto_text # Forzamos la búsqueda de forwarder en el bloque BillTo

    # --- Detectar coincidencias ---
    has_mexican = re.search(mexican_name_pattern, text, flags=I)
    has_arrow = re.search(arrow_pattern, text, flags=I)
    has_villarreal = re.search(villarreal_pattern, text, flags=I)
    has_bdp = re.search(bdp_pattern, text, flags=I)
    has_medina = re.search(medina_pattern, text, flags=I)

    ship_to_address = "Ship To Not Found"
    bill_to_address = "Bill To Not Found"

    # --- Detección dentro del bloque ShipTo/BillTo ---
    ship_block_mex = re.search(mexican_name_pattern, shipto_text, flags=I)
    bill_block_arrow = re.search(arrow_pattern, billto_text, flags=I)
    
    # 🎯 CASO PRINCIPAL: Hay Arrow y un cliente mexicano
    if has_mexican and has_arrow:
        
        # 1. Determinar el Nombre Mexicano
        mexican_name_match = ship_block_mex if ship_block_mex else has_mexican
        mexican_name = re.sub(r'\s+', ' ', mexican_name_match.group(0).strip())

        # 2. Asignar Bill To (USANDO bill_block_arrow)
        if bill_block_arrow:
            # Normalizamos el nombre de Arrow
            arrow_name = re.sub(r'\s+', ' ', bill_block_arrow.group(0).strip())
            
            # Revisa el código postal de Arrow en el bloque Bill To
            if re.search(r'77354', billto_text):
                bill_to_address = f"{arrow_name}\n{ARROW_MAGNOLIA_ALT}"
            else:
                bill_to_address = f"{arrow_name}\n{ARROW_MAGNOLIA_ADDRESS}"
        else:
            # Fallback si no se encontró Arrow en el bloque Bill To, pero sí globalmente
            bill_to_address = f"Arrow Trading LLC\n{ARROW_MAGNOLIA_ALT}"


        # 3. Asignar Ship To (Usando Forwarder detectado)
        if re.search(medina_pattern, shipto_text, flags=I) or has_medina:
            ship_to_address = f"{mexican_name} SA de CV\n{LAREDO_ADDRESS}"
        elif re.search(villarreal_pattern, shipto_text, flags=I) or has_villarreal:
            ship_to_address = f"{mexican_name} SA de CV\n{EAGLE_PASS_ADDRESS}"
        elif re.search(bdp_pattern, shipto_text, flags=I) or has_bdp:
            ship_to_address = f"{mexican_name} SA de CV\n{REYMA_US_SHIPTO_ADDRESS}"
        else:
            ship_to_address = f"{mexican_name} SA de CV\n{REYMA_US_SHIPTO_ADDRESS}" 

    # --- Fallbacks de un solo cliente (Lógica se mantiene igual) ---
    elif has_mexican:
        mexican_name = re.sub(r'\s+', ' ', has_mexican.group(0).strip())
        ship_to_address = f"{mexican_name} SA de CV\n{REYMA_US_SHIPTO_ADDRESS}"
        if "Plasticos Adheribles del Bajio" in mexican_name:
             bill_to_address = f"{mexican_name} SA de CV\n{PLASTICOS_BAJIO_MEXICO_ADDRESS}"
        else:
             bill_to_address = f"{mexican_name} SA de CV\n{REYMA_MEXICO_ADDRESS}"

    elif has_arrow:
        ship_to_address = f"Arrow Trading LLC\n{REYMA_US_SHIPTO_ADDRESS}"
        bill_to_address = f"Arrow Trading LLC\n{ARROW_MAGNOLIA_ALT}"

    # --- Limpieza final ---
    def final_cleanup(addr):
        if not addr or addr == "Ship To Not Found" or addr == "Bill To Not Found":
            return addr
        # Normalización de nombres de clientes
        addr = re.sub(r'Plasticos Adheribles del Bajio SA de CV', 'Plasticos Adheribles del Bajio S.A. de C.V.', addr)
        addr = re.sub(r'Polietilenos del Centro SA de CV', 'Polietilenos del Centro S.A. de C.V.', addr)
        addr = re.sub(r'Grupo Industrial Reyma SA de CV', 'Grupo Industrial Reyma S.A. de C.V.', addr)
        
        addr = re.sub(r'\s{2,}', ' ', addr)
        addr = re.sub(r'[\r\n]{2,}', '\n', addr)
        return addr.strip()

    return {
        "Ship To": final_cleanup(ship_to_address),
        "Bill To": final_cleanup(bill_to_address),
    }

# PASO 3
def extract_shipping_terms(text):
    """
    Extrae los términos de envío (Incoterm, Payment Terms, Fechas y Método) 
    de un bloque de texto de factura.
    
    CORRECCIÓN: Se ajusta el patrón de Due Date para mayor flexibilidad y
    se utiliza un ancla más fuerte para Method of Shipment.
    """
    pattern = re.compile(
    r"(?:Incoterm|lncoterm|lncotenn)\s*Payment\s*Terms\s*Ship\s*Date\s*Due\s*Date\s*Method\s*of\s*Shipment\s*"
    r"(?P<incoterm>.*?)\s*"
    r"(?P<payment_terms>Net\s*\d+\s*Days|Prepaid|Collect)\s*"
    # Fecha flexible: permite espacios entre los números
    r"(?P<ship_date>\d{1,2}\s*/\s*\d{1,2}\s*/?\s*\d{0,4})\s*"
    # Due Date: también tolera espacios internos
    r"(?P<due_date>\d{1,2}\s*/?\s*\d{1,2}\s*/?\s*\d{0,4})?\s*"
    # Método: hasta antes de Product No
    r"(?P<method>.*?)"
    r"(?:\s+Product\s*No)",
    re.IGNORECASE | re.DOTALL
    )

    match = pattern.search(text)
    
    if match:
        incoterm = match.group("incoterm").strip() if match.group("incoterm") else None
        payment_terms = match.group("payment_terms").strip() if match.group("payment_terms") else None
        ship_date = match.group("ship_date").strip() if match.group("ship_date") else None
        
        # Lógica para manejar el formato inconsistente de la Due Date en tu ejemplo
        due_date_raw = match.group("due_date").strip() if match.group("due_date") else None
        due_date = due_date_raw
        
        # Si la Due Date capturó texto que parece una fecha malformada seguida por el método,
        # intentamos separarlos.
        method = match.group("method").strip() if match.group("method") else None
        
        # CASO ESPECÍFICO DE TU EJEMPLO: El texto '11/2 5/25 RAILCAR' fue capturado por 'method' 
        # en tu intento original, y aquí debería ser la combinación de 'due_date' y 'method'
        # dado que el patrón de 'due_date' original falló.
        
        # Vamos a revertir el cambio a due_date y modificar solo el método, haciendo que 
        # el 'method' capture el texto restante y luego lo limpiamos si contiene una fecha.
        
        # Mejor estrategia: **ASUMIR QUE EL MÉTODO TERMINA ANTES DE LA SIGUIENTE PALABRA MAYÚSCULA/ANCLA**
        # VAMOS A USAR TU PATRÓN ORIGINAL Y APLICAR UNA LÓGICA DE POST-PROCESAMIENTO SENCILLA.
        
        # **RE-APLICACIÓN DE TU LÓGICA CON LIMPIEZA ADICIONAL**
        
        # Usamos un patrón más simple para 'due_date' que solo busca el formato estándar,
        # y si no lo encuentra, el texto restante cae en 'method'. Luego separamos la fecha del método.
        
        # Nueva ejecución con tu patrón original (para mostrar la necesidad de post-procesamiento)
        # La única modificación es hacer el grupo de due_date no codicioso: 
        # r"(?P<due_date>\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})??\s*" 
        # y hacer que el method sea codicioso, pero eso no funciona bien.
        
        # VAMOS CON LA SOLUCIÓN DE POST-PROCESAMIENTO
        
        # Dejamos el patrón *casi* como el tuyo, pero el ancla final debe ser muy fuerte:
        
        # PATRÓN FINAL (Usando el tuyo como base y ajustando el ancla final)
        
        pattern_final = re.compile(
            r"(?:Incoterm|lncoterm|lncotenn)\s*Payment\s*Terms\s*Ship\s*Date\s*Due\s*Date\s*Method\s*of\s*Shipment\s*"
            r"(?P<incoterm>.*?)\s*" 
            r"(?P<payment_terms>Net\s*\d+\s*Days|Prepaid|Collect)\s*" 
            r"(?P<ship_date>\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})\s*" 
            r"(?P<due_date>\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})?\s*"  # Este es el problema, lo mantenemos por ahora
            r"(?P<method>.*?)"
            r"(?:\s+Product\s*No)", 
            re.IGNORECASE | re.DOTALL
        )

        match_final = pattern_final.search(text)
        
        if match_final:
            incoterm = match_final.group("incoterm").strip() if match_final.group("incoterm") else None
            payment_terms = match_final.group("payment_terms").strip() if match_final.group("payment_terms") else None
            ship_date = match_final.group("ship_date").strip() if match_final.group("ship_date") else None
            due_date = match_final.group("due_date").strip() if match_final.group("due_date") else None
            method_raw = match_final.group("method").strip() if match_final.group("method") else None
            
            # LÓGICA DE POST-PROCESAMIENTO: Si due_date es None, y el método capturó la fecha, la separamos.
            if due_date is None and method_raw:
                # Patrón para la fecha inconsistente (e.g., 11/2 5/25) al inicio de la cadena del método
                date_inconsistent_pattern = re.compile(r"(\d{1,2}\s*[/]\s*\d{1,2}\s+\d{1,2}\s*/\s*\d{2,4})")
                date_match = date_inconsistent_pattern.search(method_raw)
                
                if date_match:
                    due_date = date_match.group(1).strip()
                    # El resto es el método de envío
                    method = method_raw[date_match.end():].strip()
                else:
                    method = method_raw
            else:
                method = method_raw

            # Lógica de limpieza y corrección original
            if incoterm and incoterm.endswith(':'): incoterm = incoterm[:-1].strip()
            # La lógica de LEÓN es específica de otro ejemplo, la quitamos si no es necesaria.
            # if method and method.upper() == "LEON" and "RAILCAR" in text.upper(): method = "RAILCAR"
            
            return {
                "Incoterm": incoterm, 
                "Payment Terms": payment_terms, 
                "Ship Date": ship_date,
                "Due Date": due_date, 
                "Method of Shipment": method
            }
            
    return {
        "Incoterm": None, "Payment Terms": None, "Ship Date": None, 
        "Due Date": None, "Method of Shipment": None
    }

# PASO 4    
def safe_float_conversion(value_str):
    if value_str:
        # Eliminar comas de miles y convertir a float
        return float(value_str.replace(',', ''))
    return None
        
def extract_product_detail(text):
    """
    Extrae los detalles de la línea de producto, manejando Product No. faltante, 
    y corrigiendo la extracción de Qty/U/M corrupta.
    """
    
    # 0. Limpieza y Normalización
    text_precleaned = re.sub(r'Product\s*No\.\s*\|\s*Hem\s*Gly', 'Product No. ', text, flags=re.I)
    text_precleaned = re.sub(r'[\r\n]+', ' ', text_precleaned) 
    text_precleaned = re.sub(r'[\s|]+', ' ', text_precleaned).strip()
    text_precleaned = re.sub(r'_', ' ', text_precleaned).strip()
    
    # --- 1. Aislar el Bloque de Datos del Producto ---
    prod_block_match = re.search(r"Product No\.\s*(.*?)\s*(?:Subtotal|TOTAL)", text_precleaned, re.I | re.DOTALL)
    
    if prod_block_match:
        prod_data_block = prod_block_match.group(1).strip()
        
        # 2. Limpieza de Encabezado Residual
        header_clean_pattern = r"^\s*Item\s*Qty\s*U\/M\s*Description\s*Price\s*Each\s*Amount\s*"
        prod_data_block = re.sub(header_clean_pattern, " ", prod_data_block, flags=re.I | re.DOTALL).strip()

        # 3-4. Extracción y Limpieza de Transport No.
        transport_match = re.search(r"((RAILCAR|TRUCK|VESSEL)\s*#\s*([A-Z0-9]+))", prod_data_block, re.I)
        transport_no = transport_match.group(1).strip() if transport_match else None
        clean_data_block = re.sub(r'(RAILCAR|TRUCK|VESSEL)\s*#\s*[A-Z0-9]+', '', prod_data_block, flags=re.I).strip()
        
        # --- 5. Extracción de la Línea de Producto ---
        
        product_pattern_final = re.compile(
            # Captura 1: Product No. - Hacemos el patrón alfanumérico OPCIONAL
            r"([A-Z0-9\-]+)?\s*"
            # Captura 2: Bloque combinado (AHORA DEBE INCLUIR LA CANTIDAD Y U/M)
            r"(.*?)"                      
            # Captura 3: Price Each (El número que antecede al monto total)
            r"\s+([\d,\.]+)\s*"           
            # Captura 4: Amount (El decimal que completa el monto total)
            r"([\d,]+\.\d+)"              
            , re.I | re.DOTALL
        )
        
        plm = product_pattern_final.search(clean_data_block)
        
        if plm:
            product_no = plm.group(1).strip() if plm.group(1) else None
            
            # 6. Descomponer el bloque combinado (plm.group(2))
            combined_block_raw = plm.group(2).strip()
            extracted_price_each_from_end = plm.group(3).strip() 
            extracted_amount = plm.group(4).strip()

            # 7. Descontaminación: Extraer el Precio por Unidad real (0.57500)
            price_each_match = re.search(r"([\d\.]+)\s*$", combined_block_raw) # Busca el flotante al final
            
            if price_each_match:
                item_price_each = price_each_match.group(1)
                # Elimina el precio unitario del combined_block
                combined_block = re.sub(r"\s*([\d\.]+)$", '', combined_block_raw).strip()
            else:
                item_price_each = extracted_price_each_from_end
                combined_block = combined_block_raw
            
            # --- 8. Extracción de Qty, U/M, Description (Ajuste Crítico de Qty) ---
            item_qty, um, desc = None, None, combined_block 
            
            # PATRÓN AJUSTADO: ([\d,]+) asegura que la cantidad con comas se capture como un solo grupo
            
            # Intenta Qty/U/M (195,800/LBS)
            qty_um_desc_pattern_slash = re.compile(r"([\d,]+)\s*/([A-Za-z]+)\s*(.*)", re.I | re.DOTALL)
            qty_um_desc_match = qty_um_desc_pattern_slash.search(combined_block)

            if qty_um_desc_match:
                item_qty = qty_um_desc_match.group(1).strip()
                um = qty_um_desc_match.group(2).strip()
                desc = qty_um_desc_match.group(3).strip()
            
            else:
                # Fallback para Qty U/M (195,800 LBS)
                qty_um_desc_pattern_space = re.compile(r"([\d,]+)\s+([A-Za-z]+)\s+(.*)", re.I | re.DOTALL)
                qty_um_desc_match_fb = qty_um_desc_pattern_space.search(combined_block)
                
                if qty_um_desc_match_fb:
                    item_qty = qty_um_desc_match_fb.group(1).strip()
                    um = qty_um_desc_match_fb.group(2).strip()
                    desc = qty_um_desc_match_fb.group(3).strip()
            
            # Limpieza final de la Descripción
            desc = re.sub(r'RAIL$|TRUCK$|VESSEL$', '', desc, flags=re.I).strip()

            # Reconstruir el Amount de la factura (ej: '112' + '585.00' -> '112585.00')
            if extracted_price_each_from_end.count('.') == 0 and extracted_amount.count('.') == 1:
                # Si el Price Each extraído es un entero y el Amount es un decimal, asumimos que están unidos
                full_amount = extracted_price_each_from_end + extracted_amount
            else:
                # Si el Price Each o el Amount ya tienen comas, usamos el Amount extraído
                 full_amount = extracted_amount
            
            item_qty_num = safe_float_conversion(item_qty)
            price_each_num = safe_float_conversion(item_price_each)
            amount_num = safe_float_conversion(full_amount)

            return {
                "Product No.": product_no,
                "Item Qty": item_qty_num,
                "U/M": um,
                "Description": desc,
                "Transport No.": transport_no, 
                "Price Each": price_each_num, 
                "Amount": amount_num
            }
            
    # Retorno por defecto
    return {
        "Product No.": None, "Item Qty": None, "U/M": None, "Description": None,
        "Transport No.": None, "Price Each": None, "Amount": None
    }

def extract_raildcar_v1(text):
    # Definición de patrones base
    base_pattern = r"(RAILCAR|TRUCK|VESSEL)\s*#?\s*"
    
    # --- 1. Patrón para IDs de VAGÓN (RAILCAR) - Prioridad A (Con estructura LLLLNNNN) ---
    # Busca la estructura alfanumérica típica de un vagón y permite un espacio interno.
    # [A-Z]{2,4}[A-Z0-9]{0,4}\s*[0-9]{4,} -> FPAX21 4289
    pattern_railcar_item = re.compile(
        base_pattern + r"([A-Z]{2,4}[A-Z0-9]{0,4}\s*[0-9]{4,6})",
        re.I
    )

    # --- 2. Patrón para IDs de CAMIÓN/NÚMERICOS (TRUCK/VESSEL) - Prioridad B ---
    # Captura cualquier ID alfanumérico O puramente NUMÉRICO de 4 a 10 caracteres.
    # Esto soluciona IDs cortos como '1454'.
    pattern_truck_item = re.compile(
        base_pattern + r"([A-Z0-9]{4,10})", # Longitud mínima reducida a 4
        re.I
    )
    
    # --- Lógica de Extracción ---
    transport_id_raw = None

    # A. Intentar Patrón de VAGÓN (Específico para IDs largos con letras y números)
    transport_match = pattern_railcar_item.search(text)
    if transport_match:
        transport_id_raw = transport_match.group(2).strip()
    
    # B. Intentar Patrón de CAMIÓN (Si el de vagón falla)
    if not transport_id_raw:
        transport_match = pattern_truck_item.search(text)
        if transport_match:
            transport_id_raw = transport_match.group(2).strip()

    # --- Limpieza del Resultado Final (CRUCIAL) ---

    if transport_id_raw:
        # 1. Eliminación de palabras clave pegadas: Limpia contaminantes.
        transport_no = re.sub(
            r'[\W\s]*?(CUSTID|SEALNO|SHIPPER|P\d{2}[A-Z]\d{3}|Subtotal|LOT\s*NO|SPIDSP|PRODUCT\s*NO|PPOOLLYYPP).*',
            '',
            transport_id_raw,
            flags=re.I
        )
        
        # 2. Aplicar una limpieza estricta (solo alfanumérico y un espacio opcional)
        clean_match = re.match(r"([A-Z0-9]+\s*[A-Z0-9]*)", transport_no.strip(), re.I)

        if clean_match:
            transport_id_clean = clean_match.group(1)
            # 3. Eliminar todos los espacios internos
            transport_no = re.sub(r'\s+', '', transport_id_clean)
            
            # 4. Verificación final de longitud y exclusión (Mínimo 4 caracteres)
            if len(transport_no) >= 4 and transport_no.upper() not in ["RAILCAR", "TRUCK", "VESSEL", "CUSTID", "NONE"]:
                 return transport_no
                 
    return None

# PASO 5
def extract_totals(text):
    # Nueva Regex: permite que la parte entera tenga dígitos, espacios, puntos o comas
    # y termina con un punto y dos decimales.
    # r"([\d\s,\.]+\.\d{2})"  <-- Esta es la clave
    
    # Explicación de la regex:
    # (                 -> Inicio del grupo de captura
    # [\d\s,\.]+        -> Coincide con uno o más dígitos, espacios, comas O PUNTOS (añadimos \.)
    # \.                -> Coincide con el punto decimal final (escapado)
    # \d{2}             -> Coincide con exactamente dos dígitos decimales
    # )                 -> Fin del grupo de captura

    subtotal_match = re.search(r"Subtotal\s*([\d\s,\.]+\.\d{2})", text, re.I)
    total_match = re.search(r"TOTAL\s*([\d\s,\.]+\.\d{2})", text, re.I)

    results = {}
    
    # El resto de la lógica de limpieza es crucial para el formato
    
    if subtotal_match:
        # Capturamos y limpiamos
        # Se debe limpiar *solo* lo que NO es el separador decimal final
        subtotal_str = subtotal_match.group(1).strip()
        # Elimina todos los puntos y comas *excepto* el último punto decimal (si está presente)
        # Una forma más sencilla y segura para este formato es:
        # 1. Eliminar espacios
        # 2. Eliminar TODOS los separadores de miles (puntos y comas)
        # 3. Reemplazar el último punto por un separador universal (por ejemplo, .)
        
        # Para el formato específico "114.371.50" (donde .50 son decimales)
        # La forma más fácil es eliminar todos los separadores de miles (el primer punto)
        # y dejar el separador decimal (el segundo punto).
        
        # Primero reemplazamos el *último* punto por un marcador temporal
        # y luego eliminamos todos los demás puntos y comas.
        
        # Ya que la regex asegura que los últimos 3 caracteres son .\d{2},
        # simplemente eliminamos todos los puntos y comas *previos* a esos 3 caracteres.
        
        # Estrategia de limpieza directa para `114.371.50`:
        # Eliminamos el primer punto y el separador final es el punto decimal.
        
        # Capturamos el grupo:
        valor_capturado = subtotal_match.group(1).strip()
        
        # Reemplazamos todos los puntos y comas con una cadena vacía, 
        # *excepto* el que precede a los dos decimales.
        
        # Si eliminamos *todos* los puntos y comas (que es lo que hacías antes),
        # obtenemos: "11437150"
        
        # Solución más limpia: Eliminar solo los separadores de miles.
        subtotal_limpio = valor_capturado.replace(" ", "").replace(",", "")
        
        # Si el formato es "114.371.50" (donde el segundo punto es decimal)
        # y el primer punto es de miles, simplemente eliminamos el primer punto.
        # Esto es más complejo con regex. Mantengamos la limpieza simple y estandaricemos.
        
        # Lo que necesitas es que el resultado sea "114371.50"
        # Simplificando la limpieza:
        subtotal_str = subtotal_match.group(1).strip().replace(" ", "").replace(",", "")
        # Si el número sigue conteniendo un punto (que es el separador decimal por la regex), lo dejamos.
        
        # Para tu caso "114.371.50" (el punto final es el decimal):
        # 1. Eliminar comas y espacios: "114.371.50"
        # 2. Reemplazar el punto de miles:
        
        # Una forma más segura para manejar el formato de múltiples puntos es
        # eliminar todos los puntos EXCEPTO el último (el que la regex capturó como decimal)
        
        # Convertir a cadena y limpiar separadores de miles
        valor_limpio = subtotal_match.group(1).strip().replace(" ", "")
        
        # Eliminar cualquier carácter que no sea dígito ni el último punto
        # Usamos `re.sub` para reemplazar los separadores de miles (puntos o comas)
        # que no estén inmediatamente antes de los dos decimales.
        
        # El método más directo (asumiendo que quieres el resultado en formato estándar):
        # 1. Eliminar todos los separadores de miles (puntos y comas)
        # 2. Asignar los últimos dos dígitos como decimales
        
        # Pero tu regex YA garantiza que los últimos tres caracteres son `.\d{2}`.
        # Por lo tanto, solo tenemos que eliminar los separadores de miles *del resto del número*.
        
        # Simplificación: Asume que el último punto es el separador decimal, y todo lo demás
        # (puntos, comas, espacios) son separadores de miles que deben ser eliminados.
        
        # 1. Reemplazar el punto decimal (el último) por un marcador temporal
        valor_temp = subtotal_match.group(1).strip()
        valor_temp = valor_temp[:-3].replace(".", "").replace(",", "").replace(" ", "") + valor_temp[-3:]
        
        # 2. El valor ahora está en formato '114371.50' (o '114371,50')
        subtotal_num = safe_float_conversion(valor_temp)
        results["Subtotal"] = subtotal_num
    else:
        results["Subtotal"] = None
        
    # Aplicar la misma lógica para el TOTAL
    if total_match:
        valor_temp = total_match.group(1).strip()
        valor_temp = valor_temp[:-3].replace(".", "").replace(",", "").replace(" ", "") + valor_temp[-3:]
        total_num = safe_float_conversion(valor_temp)
        results["Total"] = total_num
    else:
        results["Total"] = None
        
    return results

def extract_invoice_data(pdf_path):
    # ... (Inicialización de data) ...
    data = {
        "File": os.path.basename(pdf_path), 
        "File_path": pdf_path,
        "Invoice No": None,
        "Invoice Date": None, 
        "S/O#": None,
        "Incotenn": None, 
        "Payment Terms": None, 
        "Ship Date": None, 
        "Due Date": None,
        "Method of Shipment": None,
        "Ship To": None, 
        "Bill To": None, 
        "Subtotal": None, 
        "Total": None,
        "Product Details": []
    }
    # --- Lectura del texto (pdfplumber / OCR) ---
    # CAMBIO: Recibe el texto completo y la lista de textos por página
    full_text, pages_text = get_pdf_text_with_ocr_fallback(pdf_path)
    # ----------------------------------------------------------------------
    # PASO CLAVE: Identificar la página de la factura
    # ----------------------------------------------------------------------
    text_for_address_and_terms = find_invoice_page_text(pages_text)
    # Normalización del texto completo (para headers, detalles y totales)
    full_text_norm = re.sub(r"\r", "\n", text_for_address_and_terms)
    full_text_one = re.sub(r"[\r\n]+", " ", full_text_norm)
    # ----------------------------------------------------------------------
    # ---------- 1. HEADER (Invoice No, Invoice Date, S/O#) ----------
    # ----------------------------------------------------------------------
    # print(full_text_one)
    headers = extract_headers(full_text_one) 
    soNo = extract_so_no(full_text)
    
    data["Invoice No"] = headers.get("Invoice No")
    data["Invoice Date"] = headers.get("Invoice Date")
    data["S/O#"] = soNo.get("S/O NO")

    # ----------------------------------------------------------------------
    # ---------- 2. EXTRAER Ship To / Bill To USANDO EL TEXTO DE LA PÁGINA DE LA FACTURA ----------
    # ----------------------------------------------------------------------
    addresses = extract_shipto_billto(full_text_one)
    data["Ship To"] = addresses.get("Ship To")
    data["Bill To"] = addresses.get("Bill To")

    # ----------------------------------------------------------------------
    # ---------- 3. EXTRAER INCOTERM, PAYMENT TERMS, FECHAS, METHOD USANDO EL TEXTO DE LA PÁGINA DE LA FACTURA ----------
    # ----------------------------------------------------------------------
    results = extract_shipping_terms(full_text_one)
    data["Incotenn"] = results.get("Incoterm")
    data["Payment Terms"] = results.get("Payment Terms")
    data["Ship Date"] = results.get("Ship Date").replace(" ", "") if results.get("Ship Date") else None
    data["Due Date"] = results.get("Due Date").replace(" ", "") if results.get("Due Date") else None
    data["Method of Shipment"] = results.get("Method of Shipment")

    # ----------------------------------------------------------------------
    # ---------- 4. DETALLES DE PRODUCTO (Utiliza full_text) ----------
    # ----------------------------------------------------------------------
    products = extract_product_detail(full_text_one)
    railcar = extract_raildcar_v1(full_text)
    products["Transport No."] = railcar
    data['Product Details'] = [products]
    # ----------------------------------------------------------------------
    # ---------- 5. SUBTOTAL / TOTAL (Utiliza full_text) ----------
    # ----------------------------------------------------------------------
    totals = extract_totals(full_text_one)
    data["Subtotal"] = totals.get("Subtotal")
    data["Total"] = totals.get("Total")

    # Resultado final (ordenado)
    output_keys = [
        "File", "File_path", "Invoice No", "Invoice Date", "S/O#", "Incotenn",
        "Payment Terms", "Ship Date", "Due Date", "Method of Shipment",
        "Ship To", "Bill To", "Subtotal", "Total"
    ]
    output = {k: data.get(k) for k in output_keys}
    output["Product Details"] = data["Product Details"] if data["Product Details"] else []

    return output