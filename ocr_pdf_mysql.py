import re
import pytesseract
from pdf2image import convert_from_path
import cv2
import numpy as np
import re
# --- CONFIGURACIÓN ---
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Program Files\poppler-24.08.0\bin"

# --- FUNCIÓN: OCR + PREPROCESAMIENTO ---
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

    # (Opcional) guardar para verificar visualmente
    cv2.imwrite("debug_imagen.png", binaria)

    # OCR con configuración flexible para texto multicolumna
    config = "--psm 6"
    texto = pytesseract.image_to_string(binaria, lang='eng', config=config)

    # Guardar el texto detectado (para depuración)
    with open("texto_ocr.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    return texto

# --- FUNCIÓN: EXTRAER ENCABEZADO ---
def parsear_encabezado(texto):
    patrones = {
        "invoice_no": r"Invoice\s*No[:\s]*([A-Z0-9\-]+)",
        "invoice_date": r"Invoice\s*Date[:\s]*([\d\/\-]+)",
        "so_no": r"S\/?O[#:\s]*([A-Z0-9\-]+)"
    }

    datos = {}
    for campo, patron in patrones.items():
        match = re.search(patron, texto, re.IGNORECASE)
        datos[campo] = match.group(1).strip() if match else None
    return datos

def parsear_encabezado_v2(texto):
    patrones = {
        "invoice_no": r"(?:I?NVOICE\s*NO[:\s]*)([A-Z0-9\-]+)",
        "invoice_date": r"(?:I?NVOICE\s*DATE[:\s]*)([\d]{1,2}/[\d]{1,2}/[\d]{2,4})",
        "so_no": r"S/?O[#:\s]*([A-Z0-9\-]+)"
    }

    datos = {}
    for campo, patron in patrones.items():
        match = re.search(patron, texto, re.IGNORECASE)
        datos[campo] = match.group(1).strip() if match else None
    return datos

def parsear_encabezado_v3(texto):
    patrones = {
        # Toleramos variantes como INVOICE NO, NVOICE NO, etc.
        "invoice_no": r"(?:I?NVOICE\s*NO[:#\s]*)([A-Z0-9\-]+)",        
        # Permite espacios, guiones y variantes entre 'Invoice Date' y la fecha
        "invoice_date": r"(?:I?NVOICE\s*DATE\s*[:\-–]?\s*)(\d{1,2}/\d{1,2}/\d{2,4})",        
        # Soporta S/O, SiO, SO, con :, #, o espacios como separador
        "so_no": r"(?:S[\/i]?O[#:\s]*)([A-Z0-9\-]+)"
    }

    datos = {}
    for campo, patron in patrones.items():
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            datos[campo] = match.group(1).strip()
        else:
            datos[campo] = None

    # Log de depuración
    # if not any(datos.values()):
    #     print("❌ No se detectó ningún campo del encabezado.")
    # else:
    #     print("✅ Encabezado detectado:", datos)

    return datos

# --- FUNCIÓN: Extraer DIRECCIONES
def parsear_bill_to_ship_to_v4(texto, num_lineas=4):
    """
    Extrae las direcciones de 'Bill To' y 'Ship To' incluso si están en el mismo renglón e invertidas.
    """
    lineas = texto.splitlines()
    encabezado_idx = None

    for i, linea in enumerate(lineas):
        if re.search(r"Ship\s*To.*Bill\s*To", linea, re.IGNORECASE) or re.search(r"Bill\s*To.*Ship\s*To", linea, re.IGNORECASE):
            encabezado_idx = i
            break

    bill_to = []
    ship_to = []

    if encabezado_idx is not None:
        for offset in range(1, num_lineas + 1):
            if encabezado_idx + offset < len(lineas):
                linea = lineas[encabezado_idx + offset]
                partes = re.split(r"\|\s*", linea.strip("| "))
                if len(partes) >= 2:
                    # ⚠️ Comprobamos el orden de encabezado original
                    encabezado = lineas[encabezado_idx].lower()
                    if "ship to" in encabezado and encabezado.index("ship to") < encabezado.index("bill to"):
                        # ship_to está a la izquierda
                        ship_to.append(partes[0].strip())
                        bill_to.append(partes[1].strip())
                    else:
                        # bill_to está a la izquierda
                        bill_to.append(partes[0].strip())
                        ship_to.append(partes[1].strip())
                elif len(partes) == 1:
                    # Solo una columna, asumimos que está mal alineado
                    bill_to.append(partes[0].strip())
    return {
        "bill_to": "\n".join(bill_to).strip() if bill_to else None,
        "ship_to": "\n".join(ship_to).strip() if ship_to else None
    }

def extraer_direcciones(texto):
    lineas = texto.splitlines()

    ship_to_inicio = None
    bill_to_inicio = None

    # Encontrar índice de línea que contiene '| Ship To: | Bill To:'
    for i, linea in enumerate(lineas):
        if re.search(r"\|\s*Ship\s*To:.*\|\s*Bill\s*To:", linea, re.IGNORECASE):
            ship_to_inicio = i + 1
            break

    ship_to = []
    bill_to = []

    if ship_to_inicio is not None:
        # Asumimos que luego de esta línea hay líneas para Ship To y Bill To
        # Basado en tu ejemplo: primeras 2 líneas Ship To, siguientes 2 líneas Bill To
        # Podríamos hacer algo dinámico si encontramos líneas vacías, etc.

        # Tomamos 4 líneas después del encabezado (puedes ajustar si quieres)
        siguientes_lineas = lineas[ship_to_inicio:ship_to_inicio+6]

        # Partimos en dos bloques buscando un punto donde cambiar de Ship To a Bill To
        # En tu ejemplo, entre "Plasticos Adheribles del Bajio" y "oi BOP International" parece el cambio.

        # Para este caso simple, tomamos las primeras 2 líneas para Ship To y el resto para Bill To
        ship_to = [l for l in siguientes_lineas[:2] if l.strip()]
        bill_to = [l for l in siguientes_lineas[2:] if l.strip()]

    return {
        "ship_to": "\n".join(ship_to),
        "bill_to": "\n".join(bill_to)
    }

def extraer_direcciones_columnas(texto):
    lineas = texto.splitlines()

    # Buscar índice del encabezado
    inicio = None
    for i, linea in enumerate(lineas):
        if re.search(r"\|\s*Ship\s*To:.*\|\s*Bill\s*To:", linea, re.IGNORECASE):
            inicio = i + 1
            break

    if inicio is None:
        return {"ship_to": "", "bill_to": ""}

    ship_to_lines = []
    bill_to_lines = []

    # Leer líneas hasta encontrar algo que indique que termina el bloque (por ej. "Incoterm" u otro patrón)
    for linea in lineas[inicio:]:
        if re.search(r"Incoterm|Invoice No|ProductNo", linea, re.IGNORECASE):
            break

        # Separar la línea en dos columnas, suponiendo que están divididas por varias espacios o un pipe
        # Ajustar el split para que tome 2 partes máximo
        columnas = re.split(r"\s{3,}|\|", linea)

        if len(columnas) >= 2:
            ship_to_lines.append(columnas[0].strip())
            bill_to_lines.append(columnas[1].strip())
        else:
            # Si sólo hay una columna, asumir que es parte de Ship To (o Bill To según contexto)
            # Aquí lo dejamos para Ship To, pero se puede ajustar si quieres
            if ship_to_lines and not bill_to_lines:
                ship_to_lines.append(columnas[0].strip())
            else:
                # Si ya empezamos a llenar bill_to_lines, añadir ahí
                bill_to_lines.append(columnas[0].strip())

    # Limpiar líneas vacías y unir
    ship_to = "\n".join([l for l in ship_to_lines if l])
    bill_to = "\n".join([l for l in bill_to_lines if l])

    return {"ship_to": ship_to, "bill_to": bill_to}

# --- FUNCIÓN: EXTRAER PRODUCTOS ---
def parsear_productos_fragmento(texto):
    productos = []
    lineas = texto.splitlines()

    encabezado_idx = None
    for i, linea in enumerate(lineas):
        if "ProductNo" in linea.replace(" ", "") or "ProductNo." in linea.replace(" ", ""):
            encabezado_idx = i
            break

    if encabezado_idx is None:
        return productos

    for i in range(encabezado_idx + 1, len(lineas)):
        linea = lineas[i].strip()
        if not linea or linea.lower().startswith("subtotal"):
            break

        # Intentar separar por | y espacios
        partes = re.split(r"\||\s{2,}", linea)

        # Filtrar elementos vacíos y limpiar espacios
        partes = [p.strip() for p in partes if p.strip()]

        # Intentamos extraer campos según el ejemplo
        # Ejemplo: ['E924 193,600', 'LBS', 'High Density Polyethylene 0.43000 83,248.00']

        if len(partes) >= 3:
            # Separamos el primer elemento en product_no y qty (ej: 'E924 193,600')
            prod_qty = partes[0].split()
            if len(prod_qty) >= 2:
                product_no = prod_qty[0]
                item_qty = prod_qty[1]
            else:
                product_no = partes[0]
                item_qty = ""

            u_m = partes[1]

            # Ahora la descripción, price each y amount están en partes[2], separémoslo
            # Asumimos que el price each y amount están al final, separados por espacios
            descripcion_y_precios = partes[2].rsplit(' ', 2)

            if len(descripcion_y_precios) == 3:
                description = descripcion_y_precios[0]
                price_each = descripcion_y_precios[1]
                amount = descripcion_y_precios[2]
            else:
                description = partes[2]
                price_each = ""
                amount = ""

            producto = {
                "product_no": product_no,
                "item_qty": item_qty,
                "u_m": u_m,
                "description": description,
                "price_each": price_each,
                "amount": amount
            }
            productos.append(producto)

    return productos

def extraer_productos_con_descripcion_detalle(texto):
    lineas = texto.splitlines()
    productos = []

    encabezado_idx = None
    for i, linea in enumerate(lineas):
        if re.search(r"ProductNo\.|Hem Gly", linea, re.IGNORECASE):
            encabezado_idx = i
            break

    if encabezado_idx is None:
        print("No se encontró encabezado de productos.")
        return productos

    i = encabezado_idx + 1
    while i < len(lineas):
        linea = lineas[i].strip()
        if not linea:
            i += 1
            continue

        m = re.match(r"^([A-Z0-9\-]+)\s+([\d,]+)\s*\|(.+)$", linea)
        if m:
            product_no = m.group(1)
            item_qty = m.group(2)
            resto = m.group(3).strip()

            partes = [p.strip() for p in resto.split('|')]

            if len(partes) >= 2:
                u_m = partes[0]
                desc_precio_amount = partes[1]

                m_precio = re.search(r"([0-9.,]+)\s+([0-9.,]+)$", desc_precio_amount)
                if m_precio:
                    price_each = m_precio.group(1)
                    amount = m_precio.group(2)
                    description = desc_precio_amount[:m_precio.start()].strip()
                else:
                    price_each = ""
                    amount = ""
                    description = desc_precio_amount

                description_detail = []
                j = i + 1
                while j < len(lineas):
                    siguiente = lineas[j].strip()
                    if not siguiente:
                        break
                    if re.match(r"^[A-Z0-9\-]+\s+[\d,]+\s*\|", siguiente):
                        break
                    description_detail.append(siguiente)
                    j += 1

                productos.append({
                    "product_no": product_no,
                    "item_qty": item_qty,
                    "u_m": u_m,
                    "description": description,
                    "description_detail": " ".join(description_detail),
                    "price_each": price_each,
                    "amount": amount
                })

                i = j
            else:
                i += 1
        else:
            i += 1

    return productos

def extraer_productos_con_descripcion_detalle_v2(texto):
    lineas = texto.splitlines()
    productos = []

    encabezado_idx = None
    for i, linea in enumerate(lineas):
        # if re.search(r"ProductNo\.|Hem Gly", linea, re.IGNORECASE):
        # if re.search(r"Product\s*No[\.°]?\s*\|.*item\s+qty", linea, re.IGNORECASE):
        # if re.search(r"Product\s*No[\.°]?\s*\|.*item\s+qty", linea, re.IGNORECASE) or re.search(r"ProductNo\.|Hem\s*Gly", linea, re.IGNORECASE):
        if (
            re.search(r"Product\s*No[\.°]?\s*\|.*(item\s+qty|Wem\s+Gty|Hem\s+Gly)", linea, re.IGNORECASE)
            or re.search(r"ProductNo\.|Hem\s*Gly|Wem\s*Gty", linea, re.IGNORECASE)
        ):
            encabezado_idx = i
            break

    if encabezado_idx is None:
        print("No se encontró encabezado de productos.")
        return productos

    i = encabezado_idx + 1
    while i < len(lineas):
        linea = lineas[i].strip()
        if not linea:
            i += 1
            continue

        # ➤ Caso 1: formato tradicional con cantidad separada
        m1 = re.match(r"^([A-Z0-9\-]+)\s+([\d,]+)\s*\|(.+)$", linea)
        
        # ➤ Caso 2: formato combinado (ej. 190,200/LBS)
        m2 = re.match(r"^([A-Z0-9\-]+)\s+([\d,]+\/[A-Z]+)\s*\|(.+)$", linea)

        if m1 or m2:
            m = m1 if m1 else m2
            product_no = m.group(1)
            qty_or_qty_um = m.group(2)
            resto = m.group(3).strip()

            # Si es el caso 1, asumimos que la unidad viene después separada
            if m1:
                partes = [p.strip() for p in resto.split('|')]
                if len(partes) >= 2:
                    u_m = partes[0]
                    desc_precio_amount = partes[1]
                else:
                    u_m = ""
                    desc_precio_amount = partes[0] if partes else ""
            else:
                # En caso combinado, separa cantidad y unidad
                qty_parts = qty_or_qty_um.split('/')
                item_qty = qty_parts[0]
                u_m = qty_parts[1]
                desc_precio_amount = resto
            # Para ambos casos
            if m1:
                item_qty = qty_or_qty_um  # solo cantidad

            # Extraer precio y monto al final de la línea
            m_precio = re.search(r"([0-9.,]+)\s+([0-9.,]+)$", desc_precio_amount)
            if m_precio:
                price_each = m_precio.group(1)
                amount = m_precio.group(2)
                description = desc_precio_amount[:m_precio.start()].strip()
            else:
                price_each = ""
                amount = ""
                description = desc_precio_amount

            # Capturar línea siguiente como descripción detallada
            description_detail = []
            j = i + 1
            while j < len(lineas):
                siguiente = lineas[j].strip()
                if not siguiente:
                    break
                if re.match(r"^[A-Z0-9\-]+\s+[\d,]+(\/[A-Z]+)?\s*\|", siguiente):
                    break
                if re.match(r"^Subtotal|TOTAL", siguiente, re.IGNORECASE):
                    break
                description_detail.append(siguiente)
                j += 1

            productos.append({
                "product_no": product_no,
                "item_qty": item_qty,
                "u_m": u_m,
                "description": description,
                "description_detail": " ".join(description_detail),
                "price_each": price_each,
                "amount": amount
            })

            i = j
        else:
            i += 1

    return productos

def extraer_productos_con_descripcion_detalle_v3(texto):
    lineas = texto.splitlines()
    productos = []

    encabezado_idx = None
    for i, linea in enumerate(lineas):
        # if re.search(r"Product\s*No[\.°]?\s*\|.*item\s+qty", linea, re.IGNORECASE) or \
        #    re.search(r"ProductNo\.|Hem\s*Gly", linea, re.IGNORECASE):
        if re.search(r"Product\s*No[\.°]?\s*\|", linea, re.IGNORECASE) and \
           re.search(r"(item|hem|wem)\s+(qty|gly|gty)", linea, re.IGNORECASE):
            encabezado_idx = i
            # print(f"✅ Encabezado detectado en línea {i}: '{linea.strip()}'")
            break

    if encabezado_idx is None:
        print("❌ No se encontró encabezado de productos.")
        return productos

    i = encabezado_idx + 1
    while i < len(lineas):
        linea = lineas[i].strip()
        if not linea:
            i += 1
            continue

        # ➤ Caso 1: cantidad y unidad separadas con pipe
        m1 = re.match(r"^([A-Z0-9\-]+)\s+([\d,]+)\s*\|(.+)$", linea)

        # ➤ Caso 2: cantidad y unidad juntas, ej. 192,500/LBS o 192,500/LBS_
        m2 = re.match(r"^([A-Z0-9\-]+)\s+([\d,]+\/[A-Z]+_?)\s*\|\s*(.+)$", linea)

        if m1 or m2:
            m = m1 if m1 else m2
            product_no = m.group(1)
            qty_or_qty_um = m.group(2)
            resto = m.group(3).strip()

            if m1:
                partes = [p.strip() for p in resto.split('|')]
                if len(partes) >= 2:
                    u_m = partes[0]
                    desc_precio_amount = partes[1]
                else:
                    u_m = ""
                    desc_precio_amount = partes[0] if partes else ""
                item_qty = qty_or_qty_um  # solo número
            else:
                qty_parts = qty_or_qty_um.split('/')
                item_qty = qty_parts[0]
                u_m = qty_parts[1]
                desc_precio_amount = resto

            # Buscar precio y total al final
            m_precio = re.search(r"([0-9.,]+)\s+([0-9.,]+)$", desc_precio_amount)
            if m_precio:
                price_each = m_precio.group(1)
                amount = m_precio.group(2)
                description = desc_precio_amount[:m_precio.start()].strip()
            else:
                price_each = ""
                amount = ""
                description = desc_precio_amount

            # Buscar descripción detallada en línea siguiente
            description_detail = []
            j = i + 1
            while j < len(lineas):
                siguiente = lineas[j].strip()
                if not siguiente:
                    break
                if re.match(r"^[A-Z0-9\-]+\s+[\d,]+(\/[A-Z]+_?)?\s*\|", siguiente):
                    break
                if re.match(r"^Subtotal|TOTAL", siguiente, re.IGNORECASE):
                    break
                description_detail.append(siguiente)
                j += 1

            productos.append({
                "product_no": product_no,
                "item_qty": item_qty,
                "u_m": u_m,
                "description": description,
                "description_detail": " ".join(description_detail),
                "price_each": price_each,
                "amount": amount
            })

            i = j
        else:
            i += 1

    # if not productos:
    #     print("❌ No se encontraron productos, aunque sí se detectó encabezado.")
    # else:
    #     print(f"✅ {len(productos)} producto(s) detectado(s).")

    return productos

def extraer_productos_con_descripcion_detalle_v_combinado(texto):
    lineas = texto.splitlines()
    productos = []

    encabezado_idx = None
    for i, linea in enumerate(lineas):
        if re.search(r"Product\s*No[\.°]?\s*\|", linea, re.IGNORECASE) and \
           re.search(r"(item|hem|wem)\s+(qty|gly|gty)", linea, re.IGNORECASE):
            encabezado_idx = i
            break

    if encabezado_idx is None:
        # alternativa: buscar solo “Product No.”
        for i, linea in enumerate(lineas):
            if re.search(r"Product\s*No[\.°]?", linea, re.IGNORECASE):
                encabezado_idx = i
                break

    if encabezado_idx is None:
        # no detectado encabezado
        # print("❌ No se encontró encabezado de productos.")
        return productos

    i = encabezado_idx + 1
    while i < len(lineas):
        linea = lineas[i].strip()
        if not linea:
            i += 1
            continue

        # Primero prueba tu patrón original m1 / m2
        m1 = re.match(r"^([A-Z0-9\-]+)\s+([\d,]+)\s*\|(.+)$", linea)
        m2 = re.match(r"^([A-Z0-9\-]+)\s+([\d,]+\/[A-Z]+_?)\s*\|\s*(.+)$", linea)

        m = None
        modo = None
        if m1:
            m = m1
            modo = "original_m1"
        elif m2:
            m = m2
            modo = "original_m2"
        else:
            # prueba patrón más permisivo
            m3 = re.match(r"^([A-Z0-9\-]+)\s+([0-9,]+\)?[A-Z/]*)\s*\|\s*(.+)$", linea)
            if m3:
                m = m3
                modo = "ajustado_m3"

        if m:
            product_no = m.group(1)
            qty_or_qty_um = m.group(2)
            resto = m.group(3).strip()

            # inicializa campos
            item_qty = ""
            u_m = ""
            description = ""
            price_each = ""
            amount = ""

            if modo == "original_m1":
                item_qty = qty_or_qty_um
                partes = [p.strip() for p in resto.split('|')]
                if len(partes) >= 2:
                    u_m = partes[0]
                    desc_precio_amount = partes[1]
                else:
                    u_m = ""
                    desc_precio_amount = partes[0] if partes else ""
                # busca precio y monto
                m_precio = re.search(r"([0-9.,]+)\s+([0-9.,]+)$", desc_precio_amount)
                if m_precio:
                    price_each = m_precio.group(1)
                    amount = m_precio.group(2)
                    description = desc_precio_amount[:m_precio.start()].strip()
                else:
                    description = desc_precio_amount

            elif modo == "original_m2":
                # your original logic
                qty_parts = qty_or_qty_um.split('/')
                item_qty = qty_parts[0]
                u_m = qty_parts[1] if len(qty_parts) > 1 else ""
                desc_precio_amount = resto
                m_precio = re.search(r"([0-9.,]+)\s+([0-9.,]+)$", desc_precio_amount)
                if m_precio:
                    price_each = m_precio.group(1)
                    amount = m_precio.group(2)
                    description = desc_precio_amount[:m_precio.start()].strip()
                else:
                    description = desc_precio_amount

            elif modo == "ajustado_m3":
                # lógica del ajuste sugerido
                # separar cantidad / unidad si están unidos, con paréntesis etc.
                # ejemplo “196,100)LBS”
                qty_um = qty_or_qty_um
                m_q = re.match(r"([0-9,]+)[\)\(]*([A-Z/]+)?", qty_um)
                if m_q:
                    item_qty = m_q.group(1)
                    if m_q.group(2):
                        u_m = m_q.group(2)
                else:
                    item_qty = qty_um

                # extraer precio unitario y monto desde resto
                description = resto
                m_prec = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+([0-9,]+\.[0-9]{2})$", resto)
                if m_prec:
                    price_each = m_prec.group(1)
                    amount = m_prec.group(2)
                    description = resto[:m_prec.start()].strip()

            # descripción extendida en líneas siguientes
            description_detail = []
            j = i + 1
            while j < len(lineas):
                siguiente = lineas[j].strip()
                if not siguiente:
                    break
                # si comienza con nuevo producto probable
                if re.match(r"^[A-Z0-9\-]+\s+[\d,]+(\/[A-Z]+_?)?\s*\|", siguiente):
                    break
                if re.match(r"^Subtotal|TOTAL", siguiente, re.IGNORECASE):
                    break
                description_detail.append(siguiente)
                j += 1

            productos.append({
                "product_no": product_no,
                "item_qty": item_qty,
                "u_m": u_m,
                "description": description,
                "description_detail": " ".join(description_detail),
                "price_each": price_each,
                "amount": amount
            })

            i = j
        else:
            i += 1

    return productos


def debug_encabezado_y_productos(texto):
    lineas = texto.splitlines()
    encabezado_idx = None
    print("🔍 Buscando encabezado de productos...\n")
    for i, linea in enumerate(lineas):
        print(f"{i:02}: {linea}")
        if (
            re.search(r"Product\s*No[\.°]?\s*\|.*(item\s+qty|Wem\s+Gty|Hem\s+Gly)", linea, re.IGNORECASE)
            or re.search(r"ProductNo\.|Hem\s*Gly|Wem\s*Gty", linea, re.IGNORECASE)
        ):
            encabezado_idx = i
            print(f"\n✅ Encabezado detectado en línea {i}: '{linea}'\n")
            break

    if encabezado_idx is None:
        print("\n⛔ No se encontró encabezado de productos.\n")
    return encabezado_idx

# --- FUNCIÓN: EXTRAER BLOQUE DE TÉRMINOS ---
def parsear_terminos_regex(texto):
    """
    Extrae directamente los valores de los términos de envío mediante expresiones regulares.
    """
    terminos = {
        "incoterm": None,
        "payment_terms": None,
        "ship_date": None,
        "due_date": None,
        "method_of_shipment": None
    }

    match = re.search(
        r"(DAP[:\s\w,]+)\s+Net\s+(\d+\s+Days)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+(\w+)",
        texto
    )

    if match:
        terminos["incoterm"] = match.group(1).strip()
        terminos["payment_terms"] = match.group(2).strip()
        terminos["ship_date"] = match.group(3).strip()
        terminos["due_date"] = match.group(4).strip()
        terminos["method_of_shipment"] = match.group(5).strip()

    return terminos

def parsear_terminos_regex_v2(texto):
    """
    Extrae los términos de envío (incoterm, payment terms, fechas, método) con una expresión regular más flexible.
    """
    terminos = {
        "incoterm": None,
        "payment_terms": None,
        "ship_date": None,
        "due_date": None,
        "method_of_shipment": None
    }

    # Limpiar saltos de línea para facilitar el matching
    texto_plano = re.sub(r'\s+', ' ', texto)

    # Expresión regular más flexible
    patron = re.search(
        r"(?i)([A-Z]{3,4}[:\s][A-Z\s,]+?)\s+Net\s+(\d+\s+Days)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+([A-Z\s]+)",
        texto_plano
    )

    if patron:
        terminos["incoterm"] = patron.group(1).strip()
        terminos["payment_terms"] = patron.group(2).strip()
        terminos["ship_date"] = patron.group(3).strip()
        terminos["due_date"] = patron.group(4).strip()
        terminos["method_of_shipment"] = patron.group(5).strip()

    return terminos

# --- FUNCIÓN: Extraer totales
def extraer_totales(texto):
    subtotal = None
    total = None
    lineas = texto.splitlines()
    for linea in lineas:
        m_sub = re.search(r"Subtotal\s*[:]?[\s]*([\d,\. ]+)", linea, re.IGNORECASE)
        if m_sub:
            subtotal = m_sub.group(1).replace(',', '').replace(' ', '')
        m_total = re.search(r"Total\s*[:]?[\s]*([\d,\. ]+)", linea, re.IGNORECASE)
        if m_total:
            total = m_total.group(1).replace(',', '').replace(' ', '')
    return {"subtotal": subtotal, "total": total}

def extraer_datos_factura(texto):
    """
    Orquesta la extracción de todas las secciones de la factura.
    Devuelve un diccionario con todos los datos extraídos.
    """
    datos_encabezado = parsear_encabezado_v3(texto)
    # debug_encabezado_y_productos(texto)
    productos = extraer_productos_con_descripcion_detalle_v_combinado(texto)
    datos_terminos = parsear_terminos_regex_v2(texto)
    totales = extraer_totales(texto)

    return {
        "encabezado": datos_encabezado,
        "productos": productos,
        "terminos": datos_terminos,
        "totales": totales
    }

def procesar_factura_pdf(pdf_path, page_number = 1):
    """
    Función principal que toma la ruta de un PDF, realiza el OCR y extrae todos los datos estructurados.
    """
    # print(f"Procesando archivo: {pdf_path}")
    
    # ➤ Leer solo número de páginas
    paginas = convert_from_path(pdf_path, dpi=50)  # Baja resolución solo para contar
    num_paginas = len(paginas)
    # print(f"Total de páginas: {num_paginas}")
    # ➤ Extraer texto de la primera página
    texto = extraer_texto_ocr(pdf_path, page_number)    
    if not contiene_datos_relevantes(texto) and num_paginas > 1:
        # print("⚠️ Primera página sin datos útiles. Probando con la última...")
        texto = extraer_texto_ocr(pdf_path, page_number=num_paginas)
    # else:
    #     print("✅ Usando texto de la primera página.")
    # print(texto)
    datos_factura = extraer_datos_factura(texto)
    return datos_factura

def procesar_factura_pdf_v2(pdf_path):
    """
    Función que toma la ruta de un PDF, recorre sus páginas hasta encontrar
    la que contiene los datos relevantes, y extrae los datos estructurados.
    """
    # convertir todas las páginas (baja resolución) sólo para contar cuántas hay
    paginas = convert_from_path(pdf_path, dpi=50)
    num_paginas = len(paginas)

    datos_factura = None

    for p in range(1, num_paginas + 1):
        texto = extraer_texto_ocr(pdf_path, page_number=p)
        # verificar si esta página parece contener datos válidos
        if contiene_datos_relevantes(texto):
            # si sí tiene datos, extraemos ahí
            datos_factura = extraer_datos_factura(texto)
            # podrías guardar `datos_factura["pagina_detectada"] = p`
            break

    # si al final no se encontró ninguna página válida, como fallback usar la página 1
    if datos_factura is None:
        # opción: extraer de la primera página aunque no tenga todo
        texto = extraer_texto_ocr(pdf_path, page_number=1)
        datos_factura = extraer_datos_factura(texto)
        datos_factura["pagina_detectada"] = 1
    else:
        # si encontraste una válida, marca cuál fue
        datos_factura["pagina_detectada"] = p

    return datos_factura

def contiene_datos_relevantes(texto):
    # 🛑 Filtro explícito: si parece un certificado, descartamos
    if re.search(r"Certificate of Analysis", texto, re.IGNORECASE):
        return False

    # ✅ Factura: buscar líneas específicas, no solo palabras
    tiene_invoice_no = re.search(r"^\s*(Invoice\s*No[:\s]+[A-Z0-9\-]+)", texto, re.IGNORECASE | re.MULTILINE)
    tiene_invoice_date = re.search(r"^\s*(Invoice\s*Date[:\s]+[\d\-\/]+)", texto, re.IGNORECASE | re.MULTILINE)
    tiene_so_no = re.search(r"^\s*(S\/?O[#:\s]+[A-Z0-9\-]+)", texto, re.IGNORECASE | re.MULTILINE)

    # ✅ Términos: línea con todas las columnas
    tiene_terminos = re.search(
        r"^\s*Incoterm\s+Payment\s+Terms\s+Ship\s+Date\s+Due\s+Date\s+Method", texto,
        re.IGNORECASE | re.MULTILINE
    )

    # ✅ Encabezado de productos
    tiene_productos = re.search(
        r"^\s*Product\s*No\.?\s*\|\s*(item\s+qty|Hem\s+Gly)", texto,
        re.IGNORECASE | re.MULTILINE
    )

    return any([tiene_invoice_no, tiene_invoice_date, tiene_so_no, tiene_terminos, tiene_productos])

# --- USO PRINCIPAL ---
pdf_path = r"C:\Users\obeli\Documents\admix_projects\python\pdf_reader\NO_PROCESABLE___25-08-27___16-50-44___T-.pdf"

# Llamar a la nueva función que encapsula todo el proceso
datos_factura = procesar_factura_pdf_v2(pdf_path)

print("\n--- 🧾 DATOS DEL ENCABEZADO ---")
if not any(datos_factura["encabezado"].values()):
    print("No se encontraron datos del encabezado.")
else:
    for campo, valor in datos_factura["encabezado"].items():
        print(f"  - {campo.replace('_', ' ').title()}: {valor}")

print("\n--- 🚚 TÉRMINOS DE ENVÍO ---")
if not any(datos_factura["terminos"].values()):
    print("No se encontraron datos de términos.")
else:
    for campo, valor in datos_factura["terminos"].items():
        print(f"  - {campo.replace('_', ' ').title()}: {valor}")

print("\n--- 📦 PRODUCTOS ---")
if not datos_factura["productos"]:
    print("No se encontraron productos.")
else:
    for p in datos_factura["productos"]:
        print(f"  - Product No: {p['product_no']}")
        print(f"  - Qty: {p['item_qty']}")
        print(f"  - U/M: {p['u_m']}")
        print(f"  - Description: {p['description']}")
        print(f"  - Description Detail: {p['description_detail']}")
        print(f"  - Price Each: {p['price_each']}")
        print(f"  - Amount: {p['amount']}")
        print("--------")
print("\n--- 💰 SUBTOTAL Y TOTAL ---")
print(f"Subtotal: {datos_factura['totales']['subtotal']}")
print(f"Total: {datos_factura['totales']['total']}")   
  