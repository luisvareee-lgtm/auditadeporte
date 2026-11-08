"""Población (Censo 2022) y forma de cada municipio del sitio, desde fuentes oficiales y abiertas.

- Forma: el conjunto de datos de unidades territoriales del Estado nacional (georef, datos.gob.ar): municipios.
  Se simplifica la geometría para que el mapa sea liviano.
- Población: Censo 2022 (INDEC), cuadros por partido o departamento de cada provincia. Solo se usa cuando el
  municipio coincide con el partido o departamento (todos los de Buenos Aires y las capitales que son departamento).
  Si el departamento incluye otras localidades, queda vacío: no se estima.
Resultado: datos/municipios_geo.json. Uso: python geo_municipios.py
"""
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "AuditaDeporteBot/5.0 (observatorio civico; github.com/luisvareee-lgtm/auditadeporte)"}
# municipios cuyo territorio es el de un departamento/partido del censo: slug → nombre del departamento
DEPARTAMENTO = {"muni-almirante-brown": "Almirante Brown", "muni-avellaneda": "Avellaneda", "muni-bahia-blanca": "Bahía Blanca",
                "muni-berazategui": "Berazategui", "muni-ensenada": "Ensenada", "muni-esteban-echeverria": "Esteban Echeverría",
                "muni-general-pueyrredon": "General Pueyrredon", "muni-la-matanza": "La Matanza", "muni-la-plata": "La Plata",
                "muni-san-fernando": "San Fernando", "muni-godoy-cruz": "Godoy Cruz", "muni-mendoza": "Capital",
                "muni-corrientes": "Capital", "muni-san-miguel-de-tucuman": "Capital"}
INDEC = "https://www.indec.gob.ar/Nivel4/Tema/2/41/165"
# slug → (nombre del municipio en georef, provincia)
MUNICIPIOS = {
    "muni-almirante-brown": ("Almirante Brown", "Buenos Aires"), "muni-alta-gracia": ("Alta Gracia", "Córdoba"),
    "muni-avellaneda": ("Avellaneda", "Buenos Aires"), "muni-bahia-blanca": ("Bahía Blanca", "Buenos Aires"),
    "muni-berazategui": ("Berazategui", "Buenos Aires"), "muni-cipolletti": ("Cipolletti", "Río Negro"),
    "muni-corrientes": ("Corrientes", "Corrientes"), "muni-ensenada": ("Ensenada", "Buenos Aires"),
    "muni-esteban-echeverria": ("Esteban Echeverría", "Buenos Aires"), "muni-general-pueyrredon": ("General Pueyrredón", "Buenos Aires"),
    "muni-godoy-cruz": ("Godoy Cruz", "Mendoza"), "muni-la-matanza": ("La Matanza", "Buenos Aires"),
    "muni-la-plata": ("La Plata", "Buenos Aires"), "muni-malagueno": ("Malagueño", "Córdoba"),
    "muni-parana": ("Paraná", "Entre Ríos"), "muni-rosario": ("Rosario", "Santa Fe"),
    "muni-rio-gallegos": ("Río Gallegos", "Santa Cruz"), "muni-rio-tercero": ("Río Tercero", "Córdoba"),
    "muni-san-fernando": ("San Fernando", "Buenos Aires"), "muni-san-miguel-de-tucuman": ("San Miguel de Tucumán", "Tucumán"),
    "muni-san-salvador-de-jujuy": ("San Salvador de Jujuy", "Jujuy"), "muni-santa-fe": ("Santa Fe", "Santa Fe"),
    "muni-mendoza": ("Capital", "Mendoza"),
}
GEOJSON = ["https://infra.datos.gob.ar/georef/municipios.geojson",
           "https://infra.datos.gob.ar/catalog/modernizacion/dataset/7/distribution/7.8/download/municipios.geojson"]


def norm(t):
    t = unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\b(municipio|municipalidad|de|del|la|el)\b", " ", re.sub(r"[^a-z ]", " ", t)).split()


def bajar(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def simplificar(coords, tol):
    """Douglas-Peucker sobre un anillo, con 4 decimales."""
    if len(coords) < 5:
        return [[round(x, 4), round(y, 4)] for x, y in coords]
    def dp(pts):
        (x1, y1), (x2, y2) = pts[0], pts[-1]
        dmax, idx = 0, 0
        for i in range(1, len(pts) - 1):
            x0, y0 = pts[i]
            num = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
            den = ((y2 - y1) ** 2 + (x2 - x1) ** 2) ** 0.5 or 1e-12
            if num / den > dmax:
                dmax, idx = num / den, i
        return dp(pts[:idx + 1])[:-1] + dp(pts[idx:]) if dmax > tol else [pts[0], pts[-1]]
    pts = [tuple(c[:2]) for c in coords]
    if pts[0] == pts[-1]:                 # anillo cerrado: se simplifica en dos mitades
        m = len(pts) // 2
        out = dp(pts[:m + 1])[:-1] + dp(pts[m:])
    else:
        out = dp(pts)
    if out[0] != out[-1]:
        out.append(out[0])
    return [[round(x, 4), round(y, 4)] for x, y in out]


def geometria(g, tol=0.002):
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return {"type": "MultiPolygon", "coordinates": [[simplificar(r, tol) for r in p] for p in polys]}


def formas():
    for u in GEOJSON:
        try:
            d = json.loads(bajar(u, 300))
            print("formas:", u, len(d.get("features", [])), "municipios")
            return d["features"]
        except Exception as e:
            print("no se pudo bajar", u, str(e)[:120])
    return []


def cuadros_indec():
    """{provincia normalizada: {departamento normalizado: población 2022}} leyendo los cuadros 'variación ... por departamento'."""
    import io
    import openpyxl  # noqa
    html = bajar(INDEC, 120).decode("utf-8", "ignore")
    links = sorted(set(re.findall(r'href="([^"]+\.xlsx?)"', html, re.I)))
    print("cuadros xlsx en la página del INDEC:", len(links))
    if os.environ.get("DIAGNOSTICO"):
        for l in links:
            if re.search(r"(?i)bsas|mendoza|tucum|corrien", l) and not re.search(r"(?i)fecund|educ|salud|hogar|vivien|migra|etni|afro|indig|disca|activ|prevision|religi", l):
                print("  LINK", l)
        raise SystemExit
    res = {}
    for l in links:
        u = urllib.parse.urljoin(INDEC, l)
        if not re.search(r"(?i)c1_|cuadro.?1|variaci|_c1", u):
            continue
        try:
            wb = openpyxl.load_workbook(io.BytesIO(bajar(u, 120)), read_only=True, data_only=True)
        except Exception as e:
            print("  no se pudo leer", u, str(e)[:60]); continue
        for ws in wb.worksheets:
            filas = [list(r) for r in ws.iter_rows(values_only=True)]
            titulo = " ".join(str(c) for f in filas[:6] for c in f if c)
            m = re.search(r"(?i)provincia de ([A-Za-zÁÉÍÓÚáéíóúñÑ .]+?)[,.]|ciudad aut[oó]noma", titulo)
            if not m or not re.search(r"(?i)departamento|partido|comuna", titulo):
                continue
            prov = "caba" if "ciudad aut" in titulo.lower() else " ".join(norm(m.group(1)))
            for f in filas:
                if f and isinstance(f[0], str) and len(f) > 2:
                    nums = [c for c in f[1:] if isinstance(c, (int, float))]
                    if len(nums) >= 2:      # población 2010 y 2022 (y variaciones)
                        res.setdefault(prov, {})[" ".join(norm(f[0]))] = int(nums[1])
    print("provincias leídas:", sorted(res))
    return res


def poblacion(nombre, provincia):
    """Población del Censo 2022 en Wikidata para el municipio/partido. (valor, item, etiqueta) o None."""
    q = f'''SELECT ?it ?itLabel ?pop WHERE {{
      ?it rdfs:label "{nombre}"@es; wdt:P17 wd:Q414; p:P1082 ?st. ?st ps:P1082 ?pop; pq:P585 ?f.
      FILTER(YEAR(?f) = 2022)
      ?it wdt:P131* ?prov. ?prov rdfs:label "{provincia if provincia != 'Buenos Aires' else 'Provincia de Buenos Aires'}"@es.
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es". }} }}'''
    try:
        r = json.loads(bajar("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q), 60))
        bs = r["results"]["bindings"]
        if not bs:
            return None
        b = max(bs, key=lambda x: float(x["pop"]["value"]))       # partido > localidad homónima
        return int(float(b["pop"]["value"])), b["it"]["value"], b["itLabel"]["value"]
    except Exception as e:
        print("  wikidata:", str(e)[:100])
        return None


def main():
    fs = formas()
    try:
        cen = cuadros_indec()
    except Exception as e:
        print("no se pudo leer el INDEC:", str(e)[:120]); cen = {}
    out = {"fuente_formas": "Unidades territoriales del Estado nacional (georef, datos.gob.ar)",
           "fuente_poblacion": "Censo Nacional 2022 (INDEC), cuadros por partido o departamento", "municipios": {}}
    for slug, (nom, prov) in MUNICIPIOS.items():
        cand = [f for f in fs if norm(f["properties"].get("nombre")) == norm(nom)
                and norm((f["properties"].get("provincia") or {}).get("nombre") if isinstance(f["properties"].get("provincia"), dict)
                         else f["properties"].get("provincia_nombre") or f["properties"].get("provincia")) == norm(prov)]
        geo = geometria(cand[0]["geometry"], 0.0006) if cand and cand[0].get("geometry") else None
        pob = None
        if slug in DEPARTAMENTO:
            pob = (cen.get(" ".join(norm(prov))) or {}).get(" ".join(norm(DEPARTAMENTO[slug])))
        out["municipios"][slug] = {"nombre": nom, "provincia": prov, "poblacion_2022": pob,
                                   "nota_poblacion": None if slug in DEPARTAMENTO else "el departamento del censo incluye otras localidades",
                                   "geometria": geo}
        print(f"{slug:30} forma={'sí' if geo else 'NO'} ({sum(len(r) for p in geo['coordinates'] for r in p) if geo else 0} puntos)  población 2022={pob or '—'}")
    json.dump(out, open(os.path.join(AQUI, "..", "datos", "municipios_geo.json"), "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print("tamaño:", os.path.getsize(os.path.join(AQUI, "..", "datos", "municipios_geo.json")) // 1024, "KB")


if __name__ == "__main__":
    main()
