"""Rastreo de punta a punta de un sitio oficial (primero: Subsecretaría de Deportes de la Nación).

Recorre todas las páginas de la sección (y los documentos que enlaza), una por una y con pausa, respetando
robots.txt (o.capturar). En cada página o PDF busca temas objetivos: deporte adaptado, básquet en silla,
FABA/COPAR/ENARD, discapacidad y deporte, y fondos para selecciones (pasajes, inscripciones, becas, subsidios).
Lo que encuentra va a la cola de revisión (cola_revision), pasa por la mesa de agentes y una persona decide.
No publica nada solo, no opina y no evade bloqueos: si el sitio responde 401/403/429, se anota y se sigue otro día.

El avance queda en la tabla rastreo_paginas (db/26): cada corrida sigue donde quedó la anterior.
Uso: python rastreo_sitio.py [--sitio subsecretaria-deportes] [--max 150] [--prueba]
"""
import re
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import orquestador_bots_audita as o

AGENTE = "rastreo_sitio"
SITIOS = {
    "subsecretaria-deportes": {
        "nombre": "Subsecretaría de Deportes de la Nación",
        "semillas": ["https://www.argentina.gob.ar/jefatura/deportes"],
        # se recorre todo lo que cuelga de estas rutas; lo demás del mismo sitio solo se lee si la sección lo enlaza
        # la sección se mudó varias veces (Interior, Jefatura, Turismo y Ambiente): se recorren todas sus ubicaciones
        "prefijos": ["https://www.argentina.gob.ar/jefatura/deportes", "https://www.argentina.gob.ar/deportes",
                     "https://www.argentina.gob.ar/interior/deportes", "https://www.argentina.gob.ar/jefatura/turismo-ambiente-y-deportes",
                     "https://www.argentina.gob.ar/turismoyambiente/deportes", "https://www.argentina.gob.ar/juegosevita",
                     "https://www.argentina.gob.ar/turismoydeportes/deportes", "https://www.argentina.gob.ar/turismoydeportes/juegosevita",
                     "https://www.argentina.gob.ar/juegosadultos", "https://www.argentina.gob.ar/predios-nacionales/centro-nacional-de-alto-rendimiento-deportivo-cenard"],
        "hojas": [r"^https://www\.argentina\.gob\.ar/(noticias|normativa|node)/", r"^https://(www\.)?boletinoficial\.gob\.ar/", r"^https://www\.argentina\.gob\.ar/[a-z-]+/transparencia",
                  r"^https://servicios\.infoleg\.gob\.ar/", r"\.pdf(\?|$)"],
        "profundidad": 6,
    },
}
RE_NO_SEGUIR = re.compile(r"(?i)facebook|twitter|x\.com|instagram|youtube|whatsapp|wa\.me|t\.me|linkedin|mailto:|tel:|login|"
                          r"/user|/buscar|\?page=\d{3,}|/print/|\.(jpg|jpeg|png|gif|svg|webp|mp4|mp3|zip|rar|css|js)(\?|$)")
RE_SELEC = re.compile(r"\bselecci(on|ones)( nacional(es)?| argentina)?\b")
RE_FONDO_SEL = re.compile(r"\b(pasajes?|inscripci\w*|subsidios?|becas?|aportes?|transferencias?|delegaci\w*|viaticos?|financiamiento)\b")
TEMAS_RELEVANTES = {"deporte_adaptado", "federaciones", "discapacidad_deporte", "seleccion_fondos"}


def normalizar_url(u: str) -> str:
    """Sin fragmento ni barra final, para no visitar dos veces la misma página."""
    p = urlsplit(u)
    ruta = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme, p.netloc.lower(), ruta, p.query, ""))


def enlaces(html: str, base: str) -> list:
    out = []
    for href, _ in o.RE_ENLACE.findall(html):
        u = urljoin(base, href.strip())
        if u.startswith("http") and not RE_NO_SEGUIR.search(u):
            out.append(normalizar_url(u))
    return list(dict.fromkeys(out))


def clase(url: str, cfg: dict) -> str:
    """'seccion' (se lee y se siguen sus enlaces), 'hoja' (se lee, no se sigue) o '' (fuera de alcance)."""
    if any(url.startswith(p) for p in cfg["prefijos"]):
        return "hoja" if url.lower().endswith(".pdf") else "seccion"
    if any(re.search(rx, url, re.I) for rx in cfg["hojas"]):
        return "hoja"
    return ""


def temas(texto: str) -> list:
    """Hallazgos objetivos (los mismos temas del analista de PDF) + fondos para selecciones."""
    import analista_pdf as ap
    hs = ap.hallazgos_texto(texto)
    t = ap.normalizar(texto)
    for m in RE_SELEC.finditer(t):
        ventana = t[max(0, m.start() - 200):m.end() + 200]
        if RE_FONDO_SEL.search(ventana) and re.search(r"\b(basquet|adaptad|paralimp|silla)", ventana):
            hs.append({"tema": "seleccion_fondos", "pagina": 1, "ocr": False, "veces": 1,
                       "extracto": ap.extracto(texto, m.start(), m.end())[:600], "montos": ap.montos_cerca(texto, m.start(), m.end())})
            break
    return hs


RE_PROPIO = re.compile(r"\b(faba|basquet\w*|paralimp\w*|sillas? de ruedas|copar)\b")


def es_relevante(hs: list, texto: str = "") -> bool:
    """Las federaciones solas no alcanzan (las noticias de deporte nombran al ENARD a cada rato): tiene que aparecer
    el básquet, FABA, lo paralímpico o la silla de ruedas."""
    ts = {h["tema"] for h in hs} & TEMAS_RELEVANTES
    if ts == {"federaciones"}:
        import analista_pdf as ap
        return bool(RE_PROPIO.search(ap.normalizar(texto)))
    return bool(ts)


# ---------------------------------------------------------------- avance (db/26)
def pendientes(sitio: str, cfg: dict, prueba: bool) -> list:
    if prueba:
        return [(u, 0) for u in cfg["semillas"]]
    try:
        filas = o.db().table("rastreo_paginas").select("url,profundidad").eq("sitio", sitio).eq("estado", "pendiente") \
            .order("profundidad").limit(1000).execute().data or []
        if not filas and not o.db().table("rastreo_paginas").select("url").eq("sitio", sitio).limit(1).execute().data:
            return [(u, 0) for u in cfg["semillas"]]          # primera corrida
        return [(f["url"], f["profundidad"]) for f in filas]
    except Exception as e:
        print("sin db/26 (rastreo_paginas): se recorre solo desde la portada y no se guarda el avance:", str(e)[:100])
        return [(u, 0) for u in cfg["semillas"]]


def guardar(sitio: str, filas: list, prueba: bool):
    if prueba or not filas:
        return
    try:
        o.db().table("rastreo_paginas").upsert(filas, on_conflict="sitio,url").execute()
    except Exception as e:
        print("no se pudo guardar el avance:", str(e)[:120])


def conocidas(sitio: str, prueba: bool) -> set:
    if prueba:
        return set()
    try:
        return {f["url"] for f in o.db().table("rastreo_paginas").select("url").eq("sitio", sitio).limit(20000).execute().data or []}
    except Exception:
        return set()


def rastrear(sitio: str, maximo: int = 150, prueba: bool = False, capturar=None) -> dict:
    cfg = SITIOS[sitio]
    capturar = capturar or o.capturar
    cola, vistos = pendientes(sitio, cfg, prueba), conocidas(sitio, prueba)
    vistos |= {u for u, _ in cola}
    inst = None
    if not prueba:
        try:
            r = o.db().table("instituciones").select("id").eq("slug", sitio).execute().data
            inst = r[0]["id"] if r else None
        except Exception:
            pass
    res = {"leidas": 0, "nuevas_en_cola": 0, "bloqueadas": 0, "propuestas": 0, "temas": {}, "pendientes": 0, "fuera": {}}
    while cola and res["leidas"] < maximo and not o.tiempo_agotado():
        url, prof = cola.pop(0)
        cap = capturar(url)
        res["leidas"] += 1
        fila = {"sitio": sitio, "url": url, "profundidad": prof, "estado": "visto", "http": cap.http,
                "sha256": cap.sha256 or None, "visto_en": o.ahora().isoformat()}
        if cap.http in (401, 403, 429) or cap.motivo == "robots_no_permite":
            res["bloqueadas"] += 1
            fila["estado"] = "bloqueado"
            guardar(sitio, [fila], prueba)
            continue
        if cap.http != 200 or not cap.contenido:
            fila["estado"] = "error"
            guardar(sitio, [fila], prueba)
            continue
        es_pdf = cap.contenido[:5] == b"%PDF-"
        texto = (o.texto_pdf(cap.contenido) or "") if es_pdf else o.texto_html(cap.contenido)
        hs = temas(texto)
        fila["temas"] = sorted({h["tema"] for h in hs})
        for t in fila["temas"]:
            res["temas"][t] = res["temas"].get(t, 0) + 1
        nuevas = []
        if not es_pdf and clase(url, cfg) == "seccion" and prof < cfg["profundidad"]:
            for u in enlaces(cap.contenido.decode("utf-8", "ignore"), url):
                if not clase(u, cfg):
                    p = urlsplit(u)
                    clave = p.netloc + "/" + p.path.strip("/").split("/")[0] + ("/" + p.path.strip("/").split("/")[1] if p.path.count("/") > 1 else "")
                    res["fuera"][clave] = res["fuera"].get(clave, 0) + 1
                if u not in vistos and clase(u, cfg):
                    vistos.add(u)
                    cola.append((u, prof + 1))
                    nuevas.append({"sitio": sitio, "url": u, "profundidad": prof + 1, "estado": "pendiente"})
        res["nuevas_en_cola"] += len(nuevas)
        guardar(sitio, [fila] + nuevas, prueba)
        if es_relevante(hs, texto):
            titulo = re.search(r"<title[^>]*>(.*?)</title>", cap.contenido.decode("utf-8", "ignore"), re.I | re.S)
            titulo = re.sub(r"\s+", " ", titulo.group(1)).strip() if titulo and not es_pdf else o.nombre_desde_url(url)
            print(f"  HALLAZGO {url} → {', '.join(fila['temas'])}", flush=True)
            if not prueba:
                import analista_pdf as ap
                r = o.proponer(AGENTE, "propuesta_cambio", f"{cfg['nombre']}: {titulo}"[:300], cap, None, inst,
                               {"sitio": sitio, "temas": fila["temas"], "hallazgos": ap.resumen_hallazgos(hs),
                                "es_pdf": es_pdf, "accion_sugerida": "revisar el documento y, si corresponde, cargarlo como fuente"},
                               texto[:4000])
                res["propuestas"] += r == "nuevo"
        time.sleep(o.PAUSA_SEG)
    res["pendientes"] = len(cola)
    res["fuera"] = dict(sorted(res["fuera"].items(), key=lambda x: -x[1])[:25])   # para ajustar el alcance
    return res


def main():
    sitio = sys.argv[sys.argv.index("--sitio") + 1] if "--sitio" in sys.argv else "subsecretaria-deportes"
    maximo = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 150
    prueba = "--prueba" in sys.argv
    o._FIN[0] = time.monotonic() + 35 * 60
    res = rastrear(sitio, maximo, prueba)
    print("RESUMEN:", res)


if __name__ == "__main__":
    main()
