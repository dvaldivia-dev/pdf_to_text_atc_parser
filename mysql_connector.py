import mysql.connector
from mysql.connector import Error

from commons import format_date_to_sql

# --- CONFIGURACIÓN DE LA BASE DE DATOS (al servidor 99) ---
DB_CONFIG = {
    'host': 'localhost', #192.168.0.99 <--- Server 99
    'database': 'atc',
    'user': 'root',
    'password': 'Kr3st0n', #Kr3st0n <--- contraseña mysql server 99
}
# --------------------------------------------------------
def insert_invoice_with_connection(conn, invoice_data: dict):
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
