import csv
import io
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# MR. BLACK RIVER MONITOR
# Fuentes: INA y Servicio de Hidrografia Naval

URL_INA = "https://alerta.ina.gob.ar/pub/datos/datos"
URL_SHN = "https://www.hidro.gov.ar/oceanografia/AlturasHorarias.asp?export=csv"

ARCHIVO = Path("ultimo_estado.json")
HISTORIAL = Path("historial_san_fernando.json")
UMBRAL_ALERTA = 0.50
ZONA_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")


def descargar(url):
    solicitud = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*"
        }
    )
    with urllib.request.urlopen(solicitud, timeout=30) as respuesta:
        return respuesta.read()


def consultar_ina():
    hoy = datetime.now(ZONA_ARGENTINA).date()
    inicio = hoy - timedelta(days=10)
    fin = hoy + timedelta(days=1)

    url = (
        f"{URL_INA}&timeStart={inicio}"
        f"&timeEnd={fin}"
        "&seriesId=50"
        "&siteCode=50"
        "&varId=2"
        "&format=json"
    )

    respuesta = json.loads(descargar(url).decode("utf-8"))
    datos = [
        d for d in respuesta.get("data", [])
        if d.get("valor") is not None and d.get("timestart")
    ]

    if not datos:
        raise RuntimeError("INA no devolvio mediciones")

    datos.sort(key=lambda d: d["timestart"])

    ultimo = datos[-1]
    anterior = datos[-2] if len(datos) > 1 else None

    altura = float(ultimo["valor"])
    diferencia = (
        round(altura - float(anterior["valor"]), 2)
        if anterior else None
    )

    if diferencia is None:
        tendencia = "SIN DATOS ANTERIORES"
    elif diferencia > 0:
        tendencia = "SUBIO"
    elif diferencia < 0:
        tendencia = "BAJO"
    else:
        tendencia = "SIN CAMBIOS"

    return {
        "altura_m": altura,
        "fecha_medicion": ultimo["timestart"],
        "fecha_actualizacion": ultimo.get("timeupdate"),
        "altura_anterior_m": (
            float(anterior["valor"]) if anterior else None
        ),
        "diferencia_m": diferencia,
        "tendencia": tendencia,
        "alerta": altura < UMBRAL_ALERTA,
        "umbral_alerta_m": UMBRAL_ALERTA
    }


def consultar_san_fernando():
    contenido = descargar(URL_SHN)

    # El CSV del SHN utiliza Windows-1252 y punto y coma.
    texto = contenido.decode("cp1252")
    lector = csv.DictReader(io.StringIO(texto), delimiter=";")

    if not lector.fieldnames or "San Fernando" not in lector.fieldnames:
        raise RuntimeError("No se encontro la columna San Fernando")

    mediciones = []

    for fila in lector:
        fecha_texto = (fila.get("Fecha y hora") or "").strip()
        altura_texto = (fila.get("San Fernando") or "").strip()

        if not fecha_texto or not altura_texto:
            continue

        try:
            fecha = datetime.strptime(
                fecha_texto, "%d/%m/%Y %H:%M"
            )
            altura = float(altura_texto.replace(",", "."))
        except ValueError:
            continue

        mediciones.append({
            "fecha": fecha.isoformat(),
            "altura_m": altura
        })

    if not mediciones:
        raise RuntimeError("SHN no devolvio alturas de San Fernando")

    mediciones.sort(key=lambda x: x["fecha"])

    ultimo = mediciones[-1]
    anterior = mediciones[-2] if len(mediciones) > 1 else None

    diferencia = (
        round(ultimo["altura_m"] - anterior["altura_m"], 2)
        if anterior else None
    )

    if diferencia is None:
        tendencia = "SIN DATOS ANTERIORES"
    elif diferencia > 0:
        tendencia = "SUBIENDO"
    elif diferencia < 0:
        tendencia = "BAJANDO"
    else:
        tendencia = "ESTABLE"

    return {
        "estacion": "San Fernando",
        "fuente": "Servicio de Hidrografia Naval",
        "altura_m": ultimo["altura_m"],
        "fecha_medicion": ultimo["fecha"],
        "altura_anterior_m": (
            anterior["altura_m"] if anterior else None
        ),
        "diferencia_m": diferencia,
        "tendencia": tendencia,
        "cantidad_mediciones": len(mediciones)
    }, mediciones


def ejecutar():
    ahora = datetime.now(timezone.utc)

    # Conservamos los datos existentes si alguna fuente falla.
    if ARCHIVO.exists():
        try:
            informe = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            informe = {}
    else:
        informe = {}

    informe["monitor"] = "Mr. Black River Monitor"
    informe["consulta_utc"] = ahora.isoformat()
    informe["umbral_alerta_m"] = UMBRAL_ALERTA
    informe["advertencia"] = (
        "Las alturas de San Fernando y Dique Lujan corresponden "
        "a estaciones diferentes. No equivalen a la profundidad "
        "real disponible para navegar."
    )

    fuentes_actualizadas = 0

    # DIQUE LUJAN - INA
    try:
        dique = consultar_ina()

        informe.update(dique)
        informe["estacion"] = "Dique Lujan"
        informe["siteCode"] = 50
        informe["seriesId"] = 50
        informe["dique_lujan"] = dique
        informe["ultima_consulta_ina_utc"] = ahora.isoformat()
        informe["error_ina"] = None

        fuentes_actualizadas += 1

        print("DIQUE LUJAN:", dique["altura_m"], "m")
        print("Fecha:", dique["fecha_medicion"])

    except Exception as error:
        informe["error_ina"] = str(error)
        print("ERROR INA:", error)

    # SAN FERNANDO - HIDROGRAFIA NAVAL
    try:
        san_fernando, mediciones = consultar_san_fernando()

        informe["san_fernando"] = san_fernando
        informe["ultima_consulta_shn_utc"] = ahora.isoformat()
        informe["error_shn"] = None

        HISTORIAL.write_text(
            json.dumps(
                {
                    "estacion": "San Fernando",
                    "fuente": "Servicio de Hidrografia Naval",
                    "consulta_utc": ahora.isoformat(),
                    "mediciones": mediciones
                },
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        fuentes_actualizadas += 1

        print("SAN FERNANDO:", san_fernando["altura_m"], "m")
        print("Fecha:", san_fernando["fecha_medicion"])
        print("Tendencia:", san_fernando["tendencia"])

    except Exception as error:
        informe["error_shn"] = str(error)
        print("ERROR SHN:", error)

    if fuentes_actualizadas == 0:
        raise RuntimeError(
            "No se pudo actualizar ninguna fuente. "
            "Se conserva el archivo anterior."
        )

    ARCHIVO.write_text(
        json.dumps(informe, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("Archivo actualizado:", ARCHIVO)
    print("Fuentes actualizadas:", fuentes_actualizadas)


if __name__ == "__main__":
    ejecutar()
