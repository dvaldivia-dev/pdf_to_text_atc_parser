import os
from pathlib import Path
# 1. Importar la función que quieres usar desde el otro archivo
from ocr_pdf_mysql import procesar_factura_pdf_v2
import json # Se usará para imprimir el diccionario de forma legible

def listar_pdfs_en_carpeta(carpeta):
    resultados = []
    # Usando os.walk para incluir subcarpetas, o si solo quieres los de esa carpeta, usa os.listdir
    for root, dirs, files in os.walk(carpeta):
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

def validar_datos_completos(datos):
    """
    Revisa el diccionario de datos extraídos para asegurarse de que no haya campos clave vacíos.
    Devuelve una lista con los nombres de las secciones que tienen datos faltantes.
    """
    secciones_incompletas = []

    # 1. Validar que el diccionario principal y sus claves existan
    if not datos:
        return ["Diccionario de datos vacío"]

    # 2. Validar cada sección
    if not datos.get("encabezado") or any(not v for v in datos["encabezado"].values()):
        secciones_incompletas.append("encabezado")
    
    if not datos.get("productos"):
        secciones_incompletas.append("productos")

    if not datos.get("terminos") or any(not v for v in datos["terminos"].values()):
        secciones_incompletas.append("terminos")

    if not datos.get("totales") or any(not v for v in datos["totales"].values()):
        secciones_incompletas.append("totales")

    return secciones_incompletas

# Ejemplo de uso:
carpeta = r"C:\Users\obeli\Documents\admix_projects\python\pdf_reader\pdfs"
print(carpeta)
lista_de_pdfs = listar_pdfs_en_carpeta(carpeta)

# Contadores para el resumen final
completos = 0
incompletos = 0

# 2. Iterar sobre cada PDF, procesarlo y mostrar los resultados
for info_pdf in lista_de_pdfs:
    print(f"Procesando: {info_pdf['ruta']}")
    
    # Llamar a la función importada con la ruta del PDF
    datos_extraidos = procesar_factura_pdf_v2(info_pdf['ruta'])
    
    # 3. Validar si los datos extraídos están completos
    secciones_faltantes = validar_datos_completos(datos_extraidos)

    if not secciones_faltantes:
        completos += 1
    else:
        print(f"⚠️ DATOS INCOMPLETOS en: {info_pdf['nombre_con_ext']}")
        print(f"   Secciones con datos faltantes: {', '.join(secciones_faltantes)}")
        incompletos += 1

# --- RESUMEN FINAL ---
print("\n=============================================")
print("📊 RESUMEN DEL PROCESAMIENTO")
print("=============================================")
print(f"  - Archivos completos:   {completos}")
print(f"  - Archivos incompletos: {incompletos}")
print(f"  - Total de archivos:    {len(lista_de_pdfs)}")
print("=============================================")
