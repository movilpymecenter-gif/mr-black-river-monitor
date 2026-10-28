import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# MONITOR MR. BLACK - DIQUE LUJAN
# Fuente: Instituto Nacional del Agua (INA)

URL_BASE = "https://alerta.ina.gob.ar/pub/datos/datos"
ARCHIVO = Path("ultimo_estado.json")
UMBRAL_ALERTA = 0.50


def consultar_ina():
    hoy = datetime.now(timezone.utc).date()
    inicio = hoy - timedelta(days=10)
    fin = hoy + timedelta(days=1)

    url = (
        f"{URL_BASE}&timeStart={inicio}"
        f"&timeEnd={fin}"
        "&seriesId=50"
        "&siteCode=50"
        "&varId=2"
        "&format=json"
    )

    solicitud = urllib.request.Request(
        url,
        headers={"User-Agent": "MonitorMrBlack/1.0"}
    )

    with urllib.request.urlopen(solicitud, timeout=30) as respuesta:
        return json.load(respuesta)


def ejecutar():
    respuesta = consultar_ina()
    datos = respuesta.get("data", [])

    datos = [
        d for d in datos
        if d.get("valor") is not None and d.get("timestart")
    ]

    if not datos:
        raise RuntimeError("El INA no devolvio mediciones")

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

    informe = {
        "monitor": "Mr. Black River Monitor",
        "estacion": "Dique Lujan",
        "siteCode": 50,
        "seriesId": 50,
        "consulta_utc": datetime.now(timezone.utc).isoformat(),
        "altura_m": altura,
        "fecha_medicion": ultimo["timestart"],
        "fecha_actualizacion": ultimo.get("timeupdate"),
        "altura_anterior_m": (
            float(anterior["valor"]) if anterior else None
        ),
        "diferencia_m": diferencia,
        "tendencia": tendencia,
        "alerta": altura < UMBRAL_ALERTA,
        "umbral_alerta_m": UMBRAL_ALERTA,
        "advertencia": (
            "Datos diarios. No representan la marea en tiempo real. "
            "La altura del mareografo no equivale a la profundidad "
            "real disponible para navegar."
        )
    }

    ARCHIVO.write_text(
        json.dumps(informe, indent=4, ensure_ascii=False),
        encoding="utf-8"
    )

    print("MONITOR MR. BLACK")
    print("Altura:", altura, "metros")
    print("Tendencia:", tendencia)
    print("Alerta:", informe["alerta"])
    print("Archivo actualizado:", ARCHIVO)


if __name__ == "__main__":
    ejecutar()
