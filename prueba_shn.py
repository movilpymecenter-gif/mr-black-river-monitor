import urllib.request
import csv
import io
from datetime import datetime

URL = "https://www.hidro.gov.ar/oceanografia/AlturasHorarias.asp?export=csv"

print("=" * 55)
print("MR. BLACK - PRUEBA DE HIDROGRAFIA NAVAL")
print("=" * 55)
print("Consulta:", datetime.now().isoformat())
print("URL:", URL)

try:
    solicitud = urllib.request.Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,text/plain,*/*"
        }
    )

    with urllib.request.urlopen(solicitud, timeout=30) as respuesta:
        contenido = respuesta.read()
        tipo = respuesta.headers.get("Content-Type", "")
        codigo = respuesta.status

    print("\nESTADO HTTP:", codigo)
    print("TIPO DE CONTENIDO:", tipo)
    print("TAMANO DESCARGADO:", len(contenido), "bytes")

    texto = contenido.decode("utf-8-sig", errors="replace")

    print("\nPRIMEROS 800 CARACTERES:")
    print(texto[:800])

    if "<html" in texto[:1000].lower():
        print("\nRESULTADO: Se recibio HTML, no un CSV directo.")
    else:
        filas = list(csv.reader(io.StringIO(texto)))
        print("\nFILAS DETECTADAS:", len(filas))
        print("RESULTADO: Descarga completada.")
        print("Falta verificar que las filas sean mediciones validas.")

except Exception as error:
    print("\nERROR:", repr(error))
    raise
