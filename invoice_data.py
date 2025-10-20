import os
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
import pdfplumber
from findimagespdf.pdffile import PDFFile
import pdfplumber
from pdf2image import convert_from_path
import pytesseract

def _ocr_from_pdf(pdf_path, dpi=300, lang="eng"):
    """
    Convierte todas las páginas del PDF a imágenes y aplica OCR
    para extraer texto.
    """
    text = ""
    images = convert_from_path(pdf_path, dpi)
    for img in images:
        text += pytesseract.image_to_string(img, lang=lang) + "\n"
    return text

def extract_invoice_data(pdf_path):
    """
    Versión mejorada de extracción para encabezado, términos, direcciones,
    detalles de producto y totales. Maneja errores OCR comunes (lncotenn / Incotenn),
    direcciones 'Ship To: Bill To:' en bloque, y detecta métodos de envío.
    """
    data = {
        "File": os.path.basename(pdf_path),
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
        "Transport No.": None,
        "Product Details": []
    }

    # --- Lectura del texto (pdfplumber / OCR) ---
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                full_text = ""
            else:
                # concatenamos varias páginas (hasta 3) porque COA a menudo continúa
                pages_text = []
                for i in range(min(3, len(pdf.pages))):
                    pages_text.append(pdf.pages[i].extract_text() or "")
                full_text = "\n".join(pages_text)
            if len(full_text.strip()) < 20:
                raise ValueError("Texto insuficiente — posible PDF escaneado")
    except Exception:
        # fallback a OCR si no hay texto
        full_text = _ocr_from_pdf(pdf_path)

    # print(full_text)

    # Normalizar para búsquedas
    full_text_norm = re.sub(r"\r", "\n", full_text)
    full_text_one = re.sub(r"[\r\n]+", " ", full_text_norm)

    # ---------- 0. DETECCIÓN COA ----------
    is_coa = bool(re.search(r"CERTIFICATE OF ANALYSIS|FORMOSA PLASTICS CORPORATION", full_text, re.I))

    # ---------- 1. HEADER (Invoice No, Invoice Date, S/O#) ----------
    # corregimos S/0# -> S/O#
    full_text_one = full_text_one.replace("S/0#", "S/O#")
    # patrones básicos
    m_inv = re.search(r"Invoice\s*No[:\s]*([A-Za-z0-9\-]+)", full_text_one, re.I)
    if m_inv:
        data["Invoice No"] = m_inv.group(1).strip()

    m_invdate = re.search(r"Invoice\s*Date[:\s]*([\d\-/\s]+)", full_text_one, re.I)
    if m_invdate:
        data["Invoice Date"] = re.sub(r"\s+", "", m_invdate.group(1).strip())

    m_so = re.search(r"(?:S/O#|S/O\s*NO)\s*[:\s]*([A-Za-z0-9\-]+)", full_text_one, re.I)
    if m_so:
        data["S/O#"] = m_so.group(1).strip()

    # si es COA, puede contener DATE SHIPPED
    if is_coa:
        m_shipd = re.search(r"DATE\s*SHIPPED\s*[:\s]*([\d/]+)", full_text, re.I)
        if m_shipd:
            data["Ship Date"] = m_shipd.group(1).strip()

    # ----------------------------------------------------------------------
    # ---------- 2. LIMPIEZA DE BLOQUE DE DIRECCIONES (Ajustado) ----------
    # ----------------------------------------------------------------------
    def clean_address_block(raw_text):
        if not raw_text:
            return None
        lines = []
        exclusion = re.compile(
            r"Sterling|Voice|Fax|Federal ID|Incoterm|Incotenn|lncotenn|Payment Terms|"
            r"Ship Date|Due Date|Method of Shipment|INVOICE|Product No\.|QTY|U/M|Price Each|Amount|"
            r"(?:DAT|DAP)\s*[:\s]*|Net\s*\d+\s*Days|RAILCAR|TRUCK|Subtotal|TOTAL|FORMOSA|CERTIFICATE|CUSTOMER:|RFC:", # AGREGADO: Excluir RFC: al limpiar líneas
            re.I
        )
        for ln in raw_text.splitlines():
            ln2 = re.sub(r"\s{2,}", " ", ln).strip()
            if not ln2:
                continue
            if exclusion.search(ln2):
                continue
            lines.append(ln2)
        return "\n".join(lines) if lines else None

    # ---------- 3. EXTRAER Ship To / Bill To cuando vienen juntos ----------
    # Capturamos el bloque que sigue a "Ship To" y "Bill To"
    addr_block_match = re.search(
        r"Ship\s*To\s*:?\s*Bill\s*To\s*:?\s*(.*?)(?:Incoterm|Incotenn|lncotenn|Payment\s*Terms|Product\s*No\.|Subtotal|TOTAL|FORMOSA|CUSTOMER:)",
        full_text,
        re.I | re.DOTALL
    )

    if addr_block_match:
        block = addr_block_match.group(1).strip()
        # El bloque contiene ambas direcciones separadas por el patrón de la segunda dirección
        
        # Estrategia 1: Buscar la etiqueta explícita de la segunda dirección (Bill To)
        # En el nuevo ejemplo, Bill To es "ArrowTrading LLC." y Ship To es "Plasticos Adheribles..."
        
        # Usamos el RFC: como un posible separador o indicador del fin del Bill To anterior,
        # aunque en este caso está al final del Bill To.
        
        # Separación basada en la línea que contiene el Bill To o su dirección
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        
        # Buscamos la línea que probablemente marca el inicio del Bill To
        # En el ejemplo: "ArrowTrading LLC." es la primera línea del Bill To
        # La forma más segura es usar el RFC como referencia si está mal estructurado.
        
        bill_to_idx = None
        for i, ln in enumerate(lines):
            # Asumimos que la segunda dirección es la que contiene 'ArrowTrading LLC' o similar
            if re.search(r"ArrowTrading LLC", ln, re.I):
                bill_to_idx = i
                break
            
        if bill_to_idx is not None:
            # Dividir en el índice de la segunda dirección
            ship_raw = "\n".join(lines[:bill_to_idx]).strip()
            bill_raw = "\n".join(lines[bill_to_idx:]).strip()
        else:
            # Fallback a la lógica de City/State/Zip (aunque falló en el ejemplo)
            city_state_zip_re = re.compile(r"[A-Za-z\s\.]+,\s*[A-Z]{2}\s*\d{5}", re.I)
            city_indices = [i for i, ln in enumerate(lines) if city_state_zip_re.search(ln)]

            if len(city_indices) >= 2:
                split_at = city_indices[1]
                ship_raw = "\n".join(lines[:split_at]).strip()
                bill_raw = "\n".join(lines[split_at:]).strip()
            else:
                 # Fallback: dividir por la mitad
                half = len(lines) // 2 or 1
                ship_raw = "\n".join(lines[:half]).strip()
                bill_raw = "\n".join(lines[half:]).strip()


        data["Ship To"] = clean_address_block(ship_raw)
        data["Bill To"] = clean_address_block(bill_raw)

    elif is_coa:
        # COA: CUSTOMER block
        coa_match = re.search(r"CUSTOMER:(.*?)(?:LOT\s*NO|PRODUCT|DATE\s*SHIPPED)", full_text, re.I | re.DOTALL)
        if coa_match:
            data["Ship To"] = clean_address_block(coa_match.group(1).strip())

    # ----------------------------------------------------------------------
    # ---------- 4. EXTRAER INCOTERM, PAYMENT TERMS, FECHAS, METHOD (Ajustado) ----------
    # ----------------------------------------------------------------------
    
    # buscamos bloque de términos
    terms_text_match = re.search(r"(?:lncotenn|Incotenn|Incoterm|Incotenn)\b(.{0,250})", full_text, re.I | re.DOTALL) # Aumentado el rango
    terms_text = terms_text_match.group(1) if terms_text_match else full_text_one

    # Incoterm: Buscamos DAP: o DAT: seguido por POINT (opcional) y la ubicación
    m_incoterm = re.search(
        r"(DAP|DAT)\s*POINT\s*[:\s]*([A-Za-z0-9,\s\.]+?)(?:Net\s*\d+|(?:\d{1,2}/\d{1,2}/\d{2,4})|RAILCAR|TRUCK|COMMON\s+CARRIER|Subtotal|TOTAL)", 
        terms_text, 
        re.I
    )
    # Si falla la búsqueda con POINT, probamos sin él (para el ejemplo anterior)
    if not m_incoterm:
        m_incoterm = re.search(
            r"(DAP|DAT)\s*[:\s]*([A-Za-z0-9,\s\.]+?)(?:Net\s*\d+|(?:\d{1,2}/\d{1,2}/\d{2,4})|RAILCAR|TRUCK|COMMON\s+CARRIER|Subtotal|TOTAL)", 
            terms_text, 
            re.I
        )
        
    if m_incoterm:
        # Si se encontró con "POINT", group(2) es "LAREDO"
        # Si se encontró sin "POINT" (ejemplo anterior), group(2) es "APODACA, NL"
        incoterm_type = m_incoterm.group(1).upper()
        location_raw = m_incoterm.group(2).strip()
        
        # Comprobamos si 'POINT' estaba presente en el texto
        if "POINT" in terms_text_match.group(0): # Usamos el grupo 0 para revisar si POINT está cerca
             data["Incotenn"] = f"{incoterm_type} POINT: {location_raw}"
        else:
            # Usamos la lógica del ejemplo anterior (DAT: APODACA, NL)
            data["Incotenn"] = f"{incoterm_type}: {location_raw}"
        
    
    # Payment Terms (ej. Net 60 Days)
    m_pay = re.search(r"(Net\s*\d+\s*Days)", terms_text, re.I)
    if m_pay:
        data["Payment Terms"] = m_pay.group(1).strip()

    # Fechas (buscamos dos fechas en el texto cercano)
    m_dates = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4}).{0,40}?(\d{1,2}/\d{1,2}/\d{2,4})", terms_text)
    if m_dates:
        # asumimos primera = Ship Date, segunda = Due Date (si aplica)
        data["Ship Date"] = data["Ship Date"] or m_dates.group(1).strip()
        data["Due Date"] = m_dates.group(2).strip()

    # Método de envío (RAILCAR, TRUCK, COMMON CARRIER, etc.)
    m_method = re.search(r"\b(RAILCAR|RAILCAR#\s*[A-Z0-9]+|TRUCK|COMMON\s+CARRIER|RAIL)\b", full_text, re.I)
    if m_method:
        # limpiar si viene con #
        data["Method of Shipment"] = m_method.group(1).strip().replace("#", "").strip()

    # ---------- 5. TRANSPORT No. ----------
    tm = re.search(r"RAILCAR#\s*([A-Z0-9]+)", full_text, re.I)
    if not tm:
        tm = re.search(r"RAILCAR\s*([A-Z0-9]+)", full_text, re.I)
    if not tm:
        # Ahora busco TRUCK H10018 o RAILCAR FPAX980401
        tm = re.search(r"(?:TRUCK|RAILCAR)\s*([A-Z0-9]+)", full_text, re.I)
    if not tm:
        tm = re.search(r"TRUCK#?\s*([A-Z0-9]+)", full_text, re.I)
    if tm:
        data["Transport No."] = tm.group(1).strip()

    # ---------- 6. DETALLES DE PRODUCTO (No se requiere ajuste) ----------
    # buscamos bloque entre encabezados Product No. ... Amount y el subtotal/TOTAL
    prod_block_match = re.search(r"Product\s*No\..*?Amount\s*(.*?)\s*(?:Subtotal|TOTAL)", full_text, re.I | re.DOTALL)
    if prod_block_match:
        raw_block = prod_block_match.group(1)
        # compactamos saltos y múltiples espacios
        line_clean = re.sub(r"[\r\n]+", " ", raw_block)
        line_clean = re.sub(r"\s{2,}", " ", line_clean).strip()

        # Patrón ajustado para ser más flexible si hay texto extra
        product_pattern = re.compile(
            r"([A-Z0-9\-]+)\s+([\d,]+)\s+([A-Za-z]+)\s+(.*?)\s+([\d\.]+)\s+([\d,\.]+)",
            re.I
        )
        im = product_pattern.search(line_clean)
        if im:
            desc = re.sub(r'RAILCAR#.*|TRUCK.*', '', im.group(4), flags=re.I).strip()
            data["Product Details"].append({
                "Product No.": im.group(1).strip(),
                "Item Qty": im.group(2).strip(),
                "U/M": im.group(3).strip(),
                "Description": desc,
                "Transport No.": data.get("Transport No"),
                "Price Each": im.group(5).strip(),
                "Amount": im.group(6).strip()
            })
    elif is_coa:
        # extraer producto y peso de COA
        pm = re.search(r"PRODUCT\s*:\s*([A-Za-z0-9\s\-]+)\s+WEIGHT\s*\(LB\)\s*:\s*([\d,\.]+)", full_text, re.I)
        if pm:
            data["Product Details"].append({
                "Product No.": None,
                "Item Qty": pm.group(2).strip(),
                "U/M": "LBS",
                "Description": pm.group(1).strip(),
                "Transport No.": data.get("Transport No"),
                "Price Each": None,
                "Amount": None
            })

    # ---------- 7. SUBTOTAL / TOTAL (No se requiere ajuste) ----------
    sm = re.search(r"Subtotal\s*([\d,]+\.\d{2})", full_text, re.I)
    tm2 = re.search(r"TOTAL\s*([\d,]+\.\d{2})", full_text, re.I)
    if sm:
        data["Subtotal"] = sm.group(1).strip()
    if tm2:
        data["Total"] = tm2.group(1).strip()

    # Resultado final (ordenado)
    output_keys = [
        "File", "Invoice No", "Invoice Date", "S/O#", "Incotenn",
        "Payment Terms", "Ship Date", "Due Date", "Method of Shipment",
        "Ship To", "Bill To", "Subtotal", "Total"
    ]
    output = {k: data.get(k) for k in output_keys}
    output["Product Details"] = data["Product Details"] if data["Product Details"] else []

    return output

################################################################################################################
################################################################################################################
################################################################################################################

# PRUEBAS

folder_pdfs = r"C:\Users\obeli\Documents\admix_projects\python\pdf_reader\pdfs\procesables"

def get_pdf_paths():
    resultados = []
    # Usando os.walk para incluir subcarpetas, o si solo quieres los de esa carpeta, usa os.listdir
    for root, dirs, files in os.walk(folder_pdfs):
        for nombre in files:
            if nombre.lower().endswith(".pdf"):
                ruta_completa = os.path.join(root, nombre)
                # Con pathlib para partes más limpias
                p = Path(ruta_completa)
                nombre_sin_ext = p.stem       # nombre del archivo sin extensión
                extension = p.suffix           # extensión (incluye el punto)
                resultados.append({
                    "ruta": ruta_completa,
                    "nombre_con_ext": nombre,
                    "nombre_sin_ext": nombre_sin_ext,
                    "extension": extension
                })
    return resultados

def validateInvoiceData(invoice_data):
    """
    Revisa el diccionario de datos extraídos para asegurarse de que no haya campos clave vacíos.
    Devuelve una lista con los nombres de los campos que tienen datos faltantes.
    """
    campos_faltantes = []

    # 1. Validar que el diccionario principal exista
    if not invoice_data:
        return ["Diccionario de datos vacío"]

    # 2. Definir y validar los campos clave
    # Puedes ajustar esta lista según qué campos consideres OBLIGATORIOS
    campos_obligatorios = [
        "Invoice No",
        "Invoice Date",
        "S/O#",
        "Incotenn",
        "Payment Terms",
        "Bill To",
        "Total"
    ]

    for campo in campos_obligatorios:
        # Verifica si el valor es None o una cadena vacía ('' que también podría ser un valor "falsy")
        if not invoice_data.get(campo):
            campos_faltantes.append(campo)

    # 3. Validar la lista de productos
    if not invoice_data.get("Product Details"):
        campos_faltantes.append("Product Details (lista vacía)")

    # Opcional: Podrías validar también campos como "Subtotal" o "Ship To"
    # if not invoice_data.get("Subtotal"):
    #     campos_faltantes.append("Subtotal")

    return campos_faltantes

paths = get_pdf_paths()

completos = 0
incompletos = 0
documents = paths[0:250]

for info_pdf in documents:
    print(f"Procesando: {info_pdf['ruta']}")
    
    invoice = extract_invoice_data(info_pdf['ruta'])    
    secciones_faltantes = validateInvoiceData(invoice)
    if not secciones_faltantes:
        completos += 1
    else:
        print(f"⚠️ DATOS INCOMPLETOS en: {info_pdf['nombre_con_ext']}")
        print(f"   Secciones con datos faltantes: {', '.join(secciones_faltantes)}")
        incompletos += 1

# #--- RESUMEN FINAL ---
print("\n=============================================")
print("📊 RESUMEN DEL PROCESAMIENTO")
print("=============================================")
print(f"  - Archivos completos:   {completos}")
print(f"  - Archivos incompletos: {incompletos}")
print(f"  - Total de archivos:    {len(documents)}")
print("=============================================")

################################################################################################################
################################################################################################################
################################################################################################################

#PRUEBAS

# pdf_file = r"c:\Users\obeli\Documents\admix_projects\python\pdf_reader\pdfs\procesables\41684C_P57A507.pdf"
# result = extract_invoice_data(pdf_file)
# print(json.dumps(result, indent=2))