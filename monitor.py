import csv
import unicodedata
import io
import json
import re
from html.parser import HTMLParser
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# MR. BLACK RIVER MONITOR
# Fuente: Servicio de Hidrografia Naval

URL_SHN = "https://www.hidro.gov.ar/oceanografia/AlturasHorarias.asp?export=csv"
URL_PRONOSTICO_SHN = "https://www.hidro.gov.ar/oceanografia/pronostico.asp"

ARCHIVO = Path("ultimo_estado.json")
HISTORIAL = Path("historial_san_fernando.json")
PRONOSTICO = Path("pronostico_san_fernando.json")

UMBRAL_ALERTA = 0.50
UMBRAL_ANTIGUEDAD_SHN_MIN = 60

ZONA_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")


def descargar(url, evitar_cache=False):
    if evitar_cache:
        separador = "&" if "?" in url else "?"
        url = (
            f"{url}{separador}_mrblack_ts="
            f"{int(datetime.now(timezone.utc).timestamp())}"
        )

    solicitud = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache"
        }
    )

    with urllib.request.urlopen(solicitud, timeout=30) as respuesta:
        return respuesta.read()


def normalizar_columna(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold().strip()


def consultar_estaciones_shn():
    contenido = descargar(URL_SHN, evitar_cache=True)
    texto = contenido.decode("cp1252").lstrip("\ufeff")
    lector = csv.DictReader(io.StringIO(texto), delimiter=";")
    columnas = lector.fieldnames or []
    columnas_normalizadas = {normalizar_columna(c): c for c in columnas}
    fecha_col = columnas_normalizadas.get("fecha y hora")
    if not fecha_col:
        raise RuntimeError("SHN: falta columna Fecha y hora")

    estaciones = {
        "san_fernando": ("San Fernando", ["san fernando"]),
        "pilote_norden": ("Pilote Norden", ["pilote norden", "pilote nordern"]),
        "martin_garcia": ("Martín García", ["martin garcia", "isla martin garcia"]),
    }
    seleccion = {}
    for clave, (nombre, alternativas) in estaciones.items():
        columna = next((columnas_normalizadas[a] for a in alternativas
                        if a in columnas_normalizadas), None)
        if columna is None:
            print(f"AVISO SHN: no se encontro columna {nombre}. Disponibles: {columnas}")
        seleccion[clave] = columna

    mediciones = {clave: [] for clave in estaciones}
    for fila in lector:
        try:
            fecha = datetime.strptime((fila.get(fecha_col) or "").strip(), "%d/%m/%Y %H:%M")
        except ValueError:
            continue
        for clave, columna in seleccion.items():
            if not columna:
                continue
            valor = (fila.get(columna) or "").strip()
            try:
                altura = float(valor.replace(",", "."))
            except ValueError:
                continue
            if not (-5 < altura < 10):
                continue
            mediciones[clave].append({"fecha": fecha.isoformat(), "altura_m": altura})

    resultado = {}
    ahora = datetime.now(ZONA_ARGENTINA)
    for clave, (nombre, _) in estaciones.items():
        datos = sorted(mediciones[clave], key=lambda x: x["fecha"])
        if not datos:
            resultado[clave] = None
            print(f"AVISO SHN: {nombre} sin mediciones disponibles")
            continue
        ultimo = datos[-1]
        anterior = datos[-2] if len(datos) > 1 else None
        diferencia = round(ultimo["altura_m"] - anterior["altura_m"], 2) if anterior else None
        tendencia = ("SIN DATOS ANTERIORES" if diferencia is None else
                     "SUBIENDO" if diferencia > 0 else
                     "BAJANDO" if diferencia < 0 else "ESTABLE")
        fecha_ultima = datetime.fromisoformat(ultimo["fecha"]).replace(tzinfo=ZONA_ARGENTINA)
        antiguedad = round((ahora - fecha_ultima).total_seconds() / 60, 1)
        resultado[clave] = {
            "estacion": nombre,
            "fuente": "Servicio de Hidrografia Naval",
            "altura_m": ultimo["altura_m"],
            "fecha_medicion": ultimo["fecha"],
            "altura_anterior_m": anterior["altura_m"] if anterior else None,
            "diferencia_m": diferencia,
            "tendencia": tendencia,
            "antiguedad_min": antiguedad,
            "medicion_antigua": antiguedad > UMBRAL_ANTIGUEDAD_SHN_MIN,
            "umbral_antiguedad_min": UMBRAL_ANTIGUEDAD_SHN_MIN,
            "cantidad_mediciones": len(datos),
        }
        print(f"SHN {nombre}: {ultimo['altura_m']} m; Fecha: {ultimo['fecha']}; Tendencia: {tendencia}")
    if not any(resultado.values()):
        raise RuntimeError("SHN no devolvio mediciones para ninguna de las tres estaciones")
    return resultado, mediciones["san_fernando"]


class LectorTablasSHN(HTMLParser):
    """Extrae filas de tablas HTML, incluidas celdas con texto anidado."""

    def __init__(self):
        super().__init__()
        self.filas = []
        self.en_fila = False
        self.en_celda = False
        self.celdas = []
        self.texto_celda = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.en_fila = True
            self.celdas = []
        elif tag in ("td", "th") and self.en_fila:
            self.en_celda = True
            self.texto_celda = []

    def handle_data(self, data):
        if self.en_celda:
            self.texto_celda.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.en_celda:
            self.celdas.append(
                " ".join("".join(self.texto_celda).split())
            )
            self.en_celda = False
        elif tag == "tr" and self.en_fila:
            if self.celdas:
                self.filas.append(self.celdas)
            self.en_fila = False


def extraer_pronostico_shn(html, ahora=None):
    """Lee solo el boletín oficial vigente; no infiere mareas futuras."""

    ahora = ahora or datetime.now(ZONA_ARGENTINA)

    texto = re.sub(r"<[^>]+>", " ", html)
    texto = " ".join(texto.replace("&nbsp;", " ").split())

    patron = (
        r"VALIDO\s+DESDE\s+LAS\s+(\d{1,2}:\d{2})\s*Hs\s*DE\s*"
        r"(\d{1,2}/\d{1,2}/\d{4})\s+HASTA\s+LAS\s+"
        r"(\d{1,2}:\d{2})\s*Hs\s*DE\s*(\d{1,2}/\d{1,2}/\d{4})"
    )

    m = re.search(patron, texto, re.IGNORECASE)

    if not m:
        raise ValueError(
            "No se pudo leer el período de validez del boletín SHN"
        )

    def fecha(d, h):
        return datetime.strptime(
            d + " " + h, "%d/%m/%Y %H:%M"
        ).replace(tzinfo=ZONA_ARGENTINA)

    desde = fecha(m.group(2), m.group(1))
    hasta = fecha(m.group(4), m.group(3))

    if hasta <= desde or (hasta - desde) > timedelta(hours=24):
        raise ValueError("Período de validez anómalo")

    if not (desde - timedelta(minutes=30) <= ahora <= hasta):
        raise ValueError("Boletín SHN fuera de vigencia")

    lector = LectorTablasSHN()
    lector.feed(html)

    eventos = []
    dentro = False

    for fila in lector.filas:
        if not fila or len(fila) < 5:
            continue

        lugar, estado, hora, altura, dia = [
            v.strip() for v in fila[:5]
        ]

        if lugar.upper() == "SAN FERNANDO":
            dentro = True
        elif lugar and dentro:
            break

        if not dentro:
            continue

        if estado.upper() not in ("PLEAMAR", "BAJAMAR"):
            continue

        if not re.fullmatch(r"\d{1,2}:\d{2}", hora):
            continue

        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", dia):
            continue

        try:
            instante = fecha(dia, hora)
            metros = float(altura.replace(",", "."))
        except ValueError:
            continue

        if not (-2 < metros < 8):
            continue

        eventos.append({
            "tipo": estado.upper(),
            "fecha": instante.isoformat(),
            "altura_m": metros
        })

    if not eventos:
        raise ValueError(
            "No se encontraron pleamares/bajamares de San Fernando"
        )

    return {
        "estacion": "San Fernando",
        "fuente": "Servicio de Hidrografía Naval (SHN)",
        "url_fuente": URL_PRONOSTICO_SHN,
        "valido_desde": desde.isoformat(),
        "valido_hasta": hasta.isoformat(),
        "consulta_utc": datetime.now(timezone.utc).isoformat(),
        "eventos": sorted(
            eventos,
            key=lambda e: e["fecha"]
        ),
        "advertencia": (
            "Predicción para San Fernando; no equivale "
            "a profundidad real en Canal Villanueva."
        )
    }


def consultar_pronostico_shn():
    contenido = descargar(URL_PRONOSTICO_SHN)

    return extraer_pronostico_shn(
        contenido.decode("utf-8", errors="replace")
    )


def ejecutar():
    ahora = datetime.now(timezone.utc)

    print("INICIO EJECUCION UTC:", ahora.isoformat(), flush=True)
    print(
        "INICIO EJECUCION ARG:",
        ahora.astimezone(ZONA_ARGENTINA).isoformat(),
        flush=True
    )

    # Conservamos los datos existentes si alguna fuente falla.
    if ARCHIVO.exists():
        try:
            informe = json.loads(
                ARCHIVO.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            informe = {}
    else:
        informe = {}

    informe["monitor"] = "Mr. Black River Monitor"
    informe["consulta_utc"] = ahora.isoformat()
    informe["umbral_alerta_m"] = UMBRAL_ALERTA

    informe["advertencia"] = (
        "Las alturas de las estaciones SHN no equivalen a la profundidad "
        "real disponible para navegar en Canal Villanueva."
    )

    # Eliminamos las claves INA heredadas de ejecuciones anteriores.
    for clave in ("dique_lujan", "error_ina", "ultima_consulta_ina_utc",
                  "siteCode", "seriesId", "altura_m", "fecha_medicion",
                  "fecha_actualizacion", "altura_anterior_m", "diferencia_m",
                  "tendencia", "alerta", "estacion"):
        informe.pop(clave, None)

    fuentes_actualizadas = 0
    try:
        estaciones, mediciones = consultar_estaciones_shn()
        for clave, valor in estaciones.items():
            # No publicar datos anteriores si la estación no está en el CSV.
            informe[clave] = valor
        informe["ultima_consulta_shn_utc"] = ahora.isoformat()
        informe["error_shn"] = None
        HISTORIAL.write_text(
            json.dumps({
                "estacion": "San Fernando",
                "fuente": "Servicio de Hidrografia Naval",
                "consulta_utc": ahora.isoformat(),
                "mediciones": mediciones,
            }, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        fuentes_actualizadas += 1
    except Exception as error:
        informe["error_shn"] = str(error)
        print("ERROR SHN:", error)

    # PLEAMARES Y BAJAMARES PREVISTAS - SHN
    try:
        pronostico = consultar_pronostico_shn()

        PRONOSTICO.write_text(
            json.dumps(
                pronostico,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        print(
            "PRONOSTICO SHN:",
            len(pronostico["eventos"]),
            "eventos"
        )

    except Exception as error:
        print("AVISO PRONOSTICO SHN:", error)

        # Evitar publicar boletines vencidos.
        if PRONOSTICO.exists():
            try:
                viejo = json.loads(
                    PRONOSTICO.read_text(encoding="utf-8")
                )

                hasta = datetime.fromisoformat(
                    viejo["valido_hasta"]
                )

                if datetime.now(ZONA_ARGENTINA) > hasta:
                    PRONOSTICO.unlink()

            except (OSError, ValueError, KeyError, TypeError):
                PRONOSTICO.unlink(missing_ok=True)

    if fuentes_actualizadas == 0:
        raise RuntimeError(
            "No se pudo actualizar ninguna fuente. "
            "Se conserva el archivo anterior."
        )

    ARCHIVO.write_text(
        json.dumps(
            informe,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        "FIN EJECUCION UTC:",
        datetime.now(timezone.utc).isoformat()
    )
    print("Archivo actualizado:", ARCHIVO)
    print("Fuentes actualizadas:", fuentes_actualizadas)


if __name__ == "__main__":
    ejecutar()