"""Arma el sitio: baja pronósticos, avisos del SMN y partes de aeropuertos, y deja en sitio/:
- index.html: la plantilla con todo adentro (sirve sola, también como artefacto de Claude, sin red).
- datos.json: avisos y partes sueltos, que la página publicada relee al abrirse y con «Actualizar».

Las fuentes del SMN y de los aeropuertos no dejan que una página las lea directo (no mandan permiso de origen
cruzado), así que este script hace de intermediario. Lo corre cada 15 minutos .github/workflows/actualizar.yml.
"""
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

AQUI = Path(__file__).parent
LAT, LON = -34.6037, -58.3816
AR = dt.timezone(dt.timedelta(hours=-3))
MODELOS = "ecmwf_ifs025,gfs_seamless,icon_seamless,gem_seamless,meteofrance_seamless,ukmo_seamless,jma_seamless"
AEROPUERTOS = {"SABE": "Aeroparque", "SAEZ": "Ezeiza", "SADP": "El Palomar", "SADF": "San Fernando",
               "SADM": "Morón", "SADL": "La Plata"}
CERCA_KM = 60


def bajar(url, timeout=20, intentos=4):
    req = urllib.request.Request(url, headers={"User-Agent": "lluvia-caba/1.0 (uso personal)"})
    for i in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # El SMN corta con 429 si se le pide rápido: se espera y se reintenta.
            if e.code != 429 or i == intentos - 1:
                raise
            time.sleep(10 * (i + 1))
        except (TimeoutError, urllib.error.URLError):
            if i == intentos - 1:
                raise
            time.sleep(3)


def tag(xml, name):
    m = re.search(r"<(?:cap:)?" + name + r">(.*?)</(?:cap:)?" + name + ">", xml, re.S)
    return unescape(m.group(1).strip()) if m else ""


def poligonos(xml):
    out = []
    for p in re.findall(r"<(?:cap:)?polygon>(.*?)</(?:cap:)?polygon>", xml, re.S):
        pts = [tuple(map(float, par.split(","))) for par in p.split() if "," in par]
        if len(pts) >= 3:
            out.append(pts)
    return out


def adentro(lat, lon, pts):
    dentro, j = False, len(pts) - 1
    for i in range(len(pts)):
        yi, xi = pts[i]
        yj, xj = pts[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def km(a, b):
    from math import asin, cos, radians, sin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(h))


def hora(s):
    return dt.datetime.fromisoformat(s) if s else None


NIVEL = {"Minor": "amarillo", "Moderate": "amarillo", "Severe": "naranja", "Extreme": "rojo"}


CACHE = AQUI / "cache_avisos"


def bajar_aviso(url):
    """Cada aviso del SMN tiene nombre único y no cambia: se guarda y no se vuelve a pedir."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / re.sub(r"[^\w.]", "_", url.split("/feeds/CAP/")[-1])
    if f.exists():
        return f.read_text(encoding="utf-8")
    xml = bajar(url)
    f.write_text(xml, encoding="utf-8")
    time.sleep(0.7)
    return xml


def leer_aviso(url, ahora):
    xml = bajar_aviso(url)
    corto = "avisocortoplazo" in url
    enviado, vence = hora(tag(xml, "sent")), hora(tag(xml, "expires"))
    # Los avisos a corto plazo vienen con la hora UTC rotulada como -03:00: si "se emitió" en el futuro, se corrige.
    if corto and enviado and enviado > ahora + dt.timedelta(minutes=10):
        enviado = enviado.replace(tzinfo=dt.timezone.utc).astimezone(AR)
        vence = vence.replace(tzinfo=dt.timezone.utc).astimezone(AR) if vence else None
    if not vence or vence < ahora:
        return None
    polis = poligonos(xml)
    if not polis:
        return None
    if any(adentro(LAT, LON, p) for p in polis):
        zona, dist = "capital", 0
    else:
        dist = min(km((LAT, LON), pt) for p in polis for pt in p)
        if not corto or dist > CERCA_KM:
            return None
        zona = "cerca"
    titulo = tag(xml, "headline") or tag(xml, "event")
    m = re.search(r"AVISO (AMARILLO|NARANJA|ROJO)", titulo.upper())
    nivel = m.group(1).lower() if m else NIVEL.get(tag(xml, "severity"), "amarillo")
    evento = re.sub(r"^(AVISO|ALERTA) (AMARILLO|NARANJA|ROJ[OA]|AMARILLA) POR ", "", titulo, flags=re.I)
    desde = hora(tag(xml, "onset")) or enviado
    return {"tipo": "corto" if corto else "alerta", "nivel": nivel, "evento": evento.capitalize(),
            "desde": desde.astimezone(AR).isoformat(), "hasta": vence.astimezone(AR).isoformat(),
            "zona": zona, "km": round(dist)}


def avisos(ahora):
    rss = bajar("https://ssl.smn.gob.ar/CAP/AR.php")
    urls = re.findall(r"<link>(https://ssl\.smn\.gob\.ar/feeds/CAP/[^<]+\.xml)</link>", rss)
    # De a uno, con pausa y guardando lo ya bajado: el SMN corta con 429 si se le piden muchos seguidos.
    # Los avisos a corto plazo van primero: son los que más importan si el límite corta a mitad de camino.
    urls.sort(key=lambda u: "avisocortoplazo" not in u)
    res = [_seguro(leer_aviso, u, ahora) for u in urls]
    vigentes = {re.sub(r"[^\w.]", "_", u.split("/feeds/CAP/")[-1]) for u in urls}
    for f in CACHE.glob("*"):
        if f.name not in vigentes:  # lo que el SMN ya sacó del listado no se guarda más
            f.unlink()
    vistos, out = set(), []
    for a in res:
        if a and a is not FALLO and (k := (a["tipo"], a["nivel"], a["evento"], a["hasta"], a["zona"])) not in vistos:
            vistos.add(k)
            out.append(a)
    out.sort(key=lambda a: (a["zona"] != "capital", a["tipo"] != "corto", a["desde"]))
    return out, len(urls), sum(1 for a in res if a is FALLO)


FALLO = object()


def _seguro(f, *a):
    try:
        return f(*a)
    except Exception as e:  # un aviso que no se puede leer no frena al resto, pero se cuenta: la página lo avisa
        print("  aviso sin leer:", a[0], e, file=sys.stderr)
        return FALLO


def describir(wx):
    if not wx:
        return ""
    w = wx.upper()
    fuerza = "fuerte" if "+" in w else "débil" if "-" in w else "moderada"
    if "TS" in w:
        return "tormenta" + (" con lluvia" if "RA" in w else "")
    if "RA" in w:
        return ("chaparrón " if "SH" in w else "lluvia ") + fuerza
    if "DZ" in w:
        return "llovizna"
    return ""


def partes():
    data = json.loads(bajar("https://aviationweather.gov/api/data/metar?format=json&hours=2&ids=" + ",".join(AEROPUERTOS)))
    ultimo = {}
    for m in data:
        if m["icaoId"] not in ultimo or m["obsTime"] > ultimo[m["icaoId"]]["obsTime"]:
            ultimo[m["icaoId"]] = m
    out = []
    for icao, nombre in AEROPUERTOS.items():
        m = ultimo.get(icao)
        if not m:
            continue
        cuando = dt.datetime.fromtimestamp(m["obsTime"], dt.timezone.utc).astimezone(AR)
        out.append({"lugar": nombre, "hora": cuando.isoformat(), "tiempo": describir(m.get("wxString"))})
    return out


def main():
    ahora = dt.datetime.now(AR)
    pron = json.loads(bajar(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&hourly=precipitation"
                            f"&timezone=America%2FArgentina%2FBuenos_Aires&forecast_days=3&models={MODELOS}"))
    # Si una fuente se cae, el sitio igual se publica: la página dice qué no se pudo leer.
    try:
        lista, revisados, sin_leer = avisos(ahora)
    except Exception as e:
        print("No pude leer el listado de avisos del SMN:", e, file=sys.stderr)
        lista, revisados, sin_leer = [], 0, "todos los"
    try:
        obs = partes()
    except Exception as e:
        print("No pude leer los partes de aeropuertos:", e, file=sys.stderr)
        obs = []
    snap = {"place": {"name": "Buenos Aires", "lat": LAT, "lon": LON},
            "taken": ahora.strftime("%d/%m/%Y a las %H:%M"),
            "data": {"utc_offset_seconds": pron["utc_offset_seconds"], "hourly": pron["hourly"]},
            "avisos": lista, "avisos_sin_leer": sin_leer, "partes": obs}
    sitio = AQUI / "sitio"
    sitio.mkdir(exist_ok=True)
    html = (AQUI / "plantilla.html").read_text(encoding="utf-8")
    (sitio / "index.html").write_text(html.replace("__SNAPSHOT__", json.dumps(snap, ensure_ascii=False, separators=(",", ":"))),
                                      encoding="utf-8")
    sueltos = {k: snap[k] for k in ("taken", "avisos", "avisos_sin_leer", "partes")}
    (sitio / "datos.json").write_text(json.dumps(sueltos, ensure_ascii=False), encoding="utf-8")
    print(f"{snap['taken']} · {revisados} avisos · {sin_leer} sin leer · {len(lista)} para Capital o cerca")
    for a in lista:
        print("  ", a)
    for o in obs:
        print("  ", o)


if __name__ == "__main__":
    main()
