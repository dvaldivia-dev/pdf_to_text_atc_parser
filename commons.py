import os
import json
from pathlib import Path
from email import policy
from email.header import decode_header
import datetime


def get_pdf_paths(path):
    resultados = []
    # Usando os.walk para incluir subcarpetas, o si solo quieres los de esa carpeta, usa os.listdir
    for root, dirs, files in os.walk(path):
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

    if not invoice_data.get("Product Details")[0].get('Product No.'):
        campos_faltantes.append("Product No")
    if not invoice_data.get("Product Details")[0].get('Item Qty'):
        campos_faltantes.append("Item Qty")
    if not invoice_data.get("Product Details")[0].get('U/M'):
        campos_faltantes.append("U/M")

    return campos_faltantes

# ---------- helpers (idénticos al script anterior) ----------
def safe_mkdir(path):
    os.makedirs(path, exist_ok=True)

def decode_mime_words(s):
    if not s:
        return ""
    parts = decode_header(s)
    result = []
    for bytes_, enc in parts:
        if isinstance(bytes_, str):
            result.append(bytes_)
        else:
            result.append(bytes_.decode(enc or "utf-8", errors="replace"))
    return "".join(result)

def sanitize_filename(name):
    keep = (" ", ".", "_", "-")
    return "".join(c if c.isalnum() or c in keep else "_" for c in name).strip()

def unique_path(path):
    base, ext = os.path.splitext(path)
    n, new_path = 1, path
    while os.path.exists(new_path):
        new_path = f"{base}_{n}{ext}"
        n += 1
    return new_path

def save_attachment(payload, filename, folder):
    safe_mkdir(folder)
    filename = sanitize_filename(filename)
    path = os.path.join(folder, filename)
    path = unique_path(path)
    with open(path, "wb") as f:
        f.write(payload)
    return path

def imap_date_format(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%d-%b-%Y")

def build_search_criteria(date_start, date_end=None, from_filter=None):
    start = imap_date_format(date_start)
    if date_end:
        end = imap_date_format(date_end)
    else:
        end = imap_date_format(datetime.datetime.today().strftime("%Y-%m-%d"))

    criteria = [f'SINCE "{start}"', f'BEFORE "{end}"']

    # 🔍 Soporta varios remitentes separados por ';'
    if from_filter:
        emails = [e.strip() for e in from_filter.split(";") if e.strip()]
        if len(emails) == 1:
            criteria.append(f'FROM "{emails[0]}"')
        elif len(emails) > 1:
            # Se van combinando correctamente usando OR
            or_parts = []
            for email_addr in emails:
                or_parts.append(f'FROM "{email_addr}"')

            # Construir la cadena tipo: (OR (OR FROM "a" FROM "b") FROM "c")
            or_query = or_parts[0]
            for next_part in or_parts[1:]:
                or_query = f'(OR {or_query} {next_part})'

            criteria.append(or_query)

    query = "(" + " ".join(criteria) + ")"
    return query

# HISTORY JSON helpers
def load_history(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_history(history, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4, ensure_ascii=False)

def already_processed(history, msg_id):
    return msg_id in history

def format_date_to_sql(date_str):
    """Convierte 'M/D/YY' a 'YYYY-MM-DD' o devuelve None."""
    if not date_str:
        return None
    try:
        # 1. Parsear la fecha de la factura ('1/23/25')
        dt_obj = datetime.datetime.strptime(date_str, '%m/%d/%y')
        # 2. Formatear al estándar SQL ('2025-01-23')
        return dt_obj.strftime('%Y-%m-%d')
    except:
        # Si falla el parseo (fecha inválida), puedes loguear y devolver None
        return None