import mysql.connector
from mysql.connector import Error

from commons import format_date_to_sql

# --- CONFIGURACIÓN DE LA BASE DE DATOS (AJUSTA ESTO) ---
DB_CONFIG = {
    'host': 'localhost',
    'database': 'atc',
    'user': 'root',
    'password': 'Kr3st0n000'
}
# --------------------------------------------------------

def insert_invoice_with_connection(conn, invoice_data: dict):
    """
    Inserta los datos de una factura usando una conexión MySQL existente.
    La conexión NO se abre ni se cierra dentro de esta función.
    
    :param conn: Objeto de conexión MySQL ya abierto.
    :param invoice_data: Diccionario con los datos de la factura.
    """
    try:
        cursor = conn.cursor()

        # --- 0. Preparar y Limpiar Datos Clave ---
        invoice_num = invoice_data.get('Invoice No')
        invoice_date_clean = invoice_data.get('Invoice Date').replace(' ', '').replace('.', '')
        total = float(invoice_data.get('Total', '0').replace(',', ''))
        
        # --- 1. VALIDACIÓN DE DUPLICADOS ---
        check_duplicate_sql = """
        SELECT COUNT(*)
        FROM invoices
        WHERE Num = %s 
          AND IssueDate = STR_TO_DATE(%s, '%%m/%%d/%%y') 
          AND Total = %s
        """
        
        cursor.execute(check_duplicate_sql, (invoice_num, invoice_date_clean, total))
        duplicate_count = cursor.fetchone()[0]

        if duplicate_count > 0:
            print(f"⚠️ Factura {invoice_num} ya existe (Fecha y Total coinciden). Inserción omitida.")
            cursor.close()
            return # Detener la inserción si es un duplicado

        # --- 2. Preparar e Insertar los Datos de Encabezado (si NO es duplicado) ---
        invoice_header_sql = """
        INSERT INTO invoices (
            Num, IssueDate, S0Num, lncotenn, PaymentTerms, ShipDate, DueDate, 
            MethodOfShipment, ShipTo, BillTo, ProductNo, Description, Amount, 
            UM, Notes, ItemQty, PriceOriginal, Subtotal, Total, OriginalPDFPath
        ) VALUES (
            %s, STR_TO_DATE(%s, '%%m/%%d/%%y'), %s, %s, 
            %s, STR_TO_DATE(%s, '%%m/%%d/%%y'), STR_TO_DATE(%s, '%%m/%%d/%%y'), %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        """
        
        productItem = invoice_data.get('Product Details')[0]
        
        itemQty = float(productItem.get("Item Qty").replace(',', '').replace(' ', '').replace('\n', ''))
        price = float(productItem.get("Price Each").replace(',', '').replace(' ', '').replace('\n', ''))
        amount = float(productItem.get("Amount").replace(',', '').replace(' ', '').replace('\n', ''))
        subtotal = float(invoice_data.get('Subtotal', '0').replace(',', ''))

        invoice_values = (
            invoice_num,
            invoice_date_clean,
            invoice_data.get('S/O#'),
            invoice_data.get('Incotenn'),
            invoice_data.get('Payment Terms'),
            invoice_data.get('Ship Date').replace(' ', '').replace('.', ''),
            invoice_data.get('Due Date').replace(' ', '').replace('.', ''),
            invoice_data.get('Method of Shipment'),
            invoice_data.get('Ship To'),
            invoice_data.get('Bill To'),
            productItem.get("Product No."),
            productItem.get("Description"),
            amount,
            productItem.get("U/M"),
            productItem.get("Transport No."), # Mapeado a Notes
            itemQty,
            price, 
            subtotal,
            total,
            invoice_data.get('File_path')
        )
        
        cursor.execute(invoice_header_sql, invoice_values)
        invoice_id = cursor.lastrowid 
        
        # 💡 NO SE HACE conn.commit() AQUÍ para permitir transacciones por lotes.
        print(f"✅ Factura {invoice_num} (ID: {invoice_id}) lista para confirmar.")

    except Error as e:
        print(f"❌ Error al procesar la factura {invoice_num}: {e}")
        # 💡 NO SE HACE conn.rollback() AQUÍ para permitir rollbacks en el bucle principal.
    finally:
        # Cierra el cursor en cada ejecución
        if 'cursor' in locals() and cursor is not None:
            cursor.close()

def insert_invoice_with_connection_v2(conn, invoice_data: dict):
    """
    Inserta los datos de una factura en la base de datos 'invoices'
    usando una conexión MySQL abierta.
    """

    # def safe_str(value):
    #     return str(value or "").strip().replace("  ", " ")

    try:
        cursor = conn.cursor()

        invoice_num = invoice_data.get('Invoice No')
        invoice_date = format_date_to_sql(invoice_data.get('Invoice Date'))
        total = invoice_data.get('Total') 

        # --- 1. VALIDAR DUPLICADO ---
        check_duplicate_sql = """
        SELECT COUNT(*)
        FROM invoices
        WHERE Num = %s 
          AND IssueDate = STR_TO_DATE(%s, '%%m/%%d/%%Y') 
          AND Total = %s
        """
        cursor.execute(check_duplicate_sql, (invoice_num, invoice_date, total))
        duplicate_count = cursor.fetchone()[0]

        # print(f"validando duplicados: {duplicate_count}")
        if duplicate_count > 0:
            print(f"⚠️ Factura {invoice_num} ya existe (Fecha y Total coinciden).")
            cursor.close()
            return {"status": "duplicate", "num": invoice_num}

        # --- 2. EXTRAER DETALLES DE PRODUCTO ---
        product_item = invoice_data.get('Product Details', [{}])[0]

        invoice_header_sql = """
        INSERT INTO invoices (
            Num, IssueDate, S0Num, lncotenn, PaymentTerms, 
            ShipDate, DueDate, MethodOfShipment, ShipTo, BillTo, 
            ProductNo, Description, Amount, UM, Notes, 
            ItemQty, PriceOriginal, Subtotal, Total, OriginalPDFPath, 
            AttachmentsPDFPath, needs_review
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, 
            %s, %s, %s, %s, %s, 
            %s, %s
        )
        """

        invoice_values = (
            invoice_num,
            invoice_date,
            invoice_data.get('S/O#'),
            invoice_data.get('Incotenn'),
            invoice_data.get('Payment Terms'),
            format_date_to_sql(invoice_data.get('Ship Date')),
            format_date_to_sql(invoice_data.get('Due Date')),
            invoice_data.get('Method of Shipment'),
            invoice_data.get('Ship To'),
            invoice_data.get('Bill To'),
            product_item.get("Product No."),
            product_item.get("Description"),
            product_item.get("Amount"),
            product_item.get("U/M"),
            product_item.get("Transport No."),  # mapped to Notes
            product_item.get("Item Qty"),
            product_item.get("Price Each"),
            invoice_data.get('Subtotal'),
            total,
            invoice_data.get('originPath'),
            invoice_data.get('attachmentPath'),
            invoice_data.get('needs_review')
        )

        cursor.execute(invoice_header_sql, invoice_values)
        invoice_id = cursor.lastrowid

        print(f"✅ Factura {invoice_num} insertada (ID: {invoice_id}).")
        return {"status": "ok", "invoice_id": invoice_id, "num": invoice_num}

    except Exception as e:
        print(f"❌ Error al insertar factura {invoice_data.get('Invoice No')}: {e}")
        return {"status": "error", "num": invoice_data.get('Invoice No'), "error": str(e)}

    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

# --- EJEMPLO DE USO ---
# db_conn = get_db_connection()
# insert_invoice_with_connection(db_conn, {})