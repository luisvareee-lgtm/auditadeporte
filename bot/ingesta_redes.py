"""Ingesta de novedades PÚBLICAS de COPAR, FABA y clubes/municipios, por vías permitidas:
 1) feeds RSS/Atom oficiales (sitios web, canales de YouTube);
 2) carga asistida por voluntarios (CSV con enlace a la publicación + captura de pantalla).
No se automatiza Instagram/Facebook/X con scraping: sus términos lo prohíben y los bloqueos rompen el servicio.
Todo va a cola_revision; una persona publica con db/08 aprobar_novedad()."""
import csv
import hashlib
import html
import json
import re
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import orquestador_bots_audita as o

# Completar SOLO con feeds que hayas abierto y verificado a mano, p. ej.:
# {"inst": "copar", "plataforma": "web", "url": "https://www.coparg.org.ar/feed/"},
# {"club": "cilsa-sf", "plataforma": "youtube", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=XXXX"},
FEEDS = []

RE_COLECTA = re.compile(r"\b(rifa|sorteo|bono contribucion|colecta|cbu|alias|ayudanos a viajar|vendemos|donaci[oó]n)\b", re.I)
TEMAS = {"viaje": r"\b(viaje|traslado|pasajes?|gira)\b", "balance": r"\b(balance|memoria|rendicion)\b",
         "convenio": r"\b(convenio|subsidio|beca)\b", "equipamiento": r"\b(silla|sillas|cubiertas?|repuestos?)\b",
         "competencia": r"\b(torneo|campeonato|fecha|liga|partido)\b"}


def limpiar(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def extracto(t: str, n: int = 280) -> str:
    t = limpiar(t)
    if len(t) <= n:
        return t
    return t[: n - 1].rsplit(" ", 1)[0] + "…"


def clasificar(t: str) -> dict:
    """Solo marcas OBJETIVAS del texto (no se infiere precariedad ni contradicciones)."""
    n = o._norm(t)
    return {"menciona_colecta": bool(RE_COLECTA.search(n)),
            "temas": [k for k, rx in TEMAS.items() if re.search(rx, n)]}


def parsear_feed(data: bytes) -> list:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("feed rechazado: contiene DOCTYPE/ENTITY (riesgo de XML malicioso)")
    root = ET.fromstring(data)
    items = []
    if root.tag.endswith("feed"):                                   # Atom
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in root.findall("a:entry", ns):
            link = next((l.get("href") for l in e.findall("a:link", ns) if l.get("rel", "alternate") == "alternate"), None)
            f = (e.findtext("a:published", namespaces=ns) or e.findtext("a:updated", namespaces=ns) or "")[:10]
            items.append({"titulo": limpiar(e.findtext("a:title", namespaces=ns)), "link": link, "fecha": f,
                          "texto": limpiar(e.findtext("a:summary", namespaces=ns) or e.findtext("a:content", namespaces=ns))})
    else:                                                           # RSS 2.0
        for e in root.iter("item"):
            try:
                f = parsedate_to_datetime(e.findtext("pubDate")).date().isoformat()
            except Exception:
                f = ""
            items.append({"titulo": limpiar(e.findtext("title")), "link": (e.findtext("link") or "").strip(), "fecha": f,
                          "texto": limpiar(e.findtext("description"))})
    return [i for i in items if i["link"] and i["fecha"]]


def proponer_item(it: dict, cfg: dict, clubes: dict, insts: dict, origen: str) -> str:
    cid, iid = clubes.get(cfg.get("club")), insts.get(cfg.get("inst"))
    if (cid is None) == (iid is None):
        return "destino_inexistente"
    cuerpo = json.dumps({k: it[k] for k in ("titulo", "link", "fecha", "texto")}, sort_keys=True, ensure_ascii=False).encode()
    cap = o.Captura(it["link"], 200, cuerpo, hashlib.sha256(cuerpo).hexdigest())   # hash del contenido recibido
    texto = f"{it['titulo']}. {it['texto']}"
    prop = {"plataforma": cfg["plataforma"], "fecha_posteo": it["fecha"], "extracto": extracto(texto),
            "origen": origen, **clasificar(texto)}
    return o.proponer("ingesta_redes", "novedad_red", it["titulo"][:200] or "Novedad", cap, cid, iid, prop, texto)


def procesar_feed(cfg: dict, clubes: dict, insts: dict, max_items=20, dias=90) -> dict:
    cap = o.capturar(cfg["url"])
    if cap.bloqueada or not cap.utilizable:
        return {"url": cfg["url"], "resultado": "bloqueado" if cap.bloqueada else (cap.motivo or f"http_{cap.http}")}
    try:
        items = parsear_feed(cap.contenido)
    except Exception as e:
        return {"url": cfg["url"], "resultado": f"feed_invalido:{e}"}
    limite = (date.today() - timedelta(days=dias)).isoformat()
    res = [proponer_item(i, cfg, clubes, insts, "rss") for i in items[:max_items] if i["fecha"] >= limite]
    return {"url": cfg["url"], "resultado": "ok", "nuevos": res.count("nuevo"), "bloqueados": res.count("bloqueado_legal"),
            "duplicados": res.count("duplicado")}


def cargar_csv(path: str, clubes: dict, insts: dict) -> list:
    """Columnas: club_slug|inst_slug, plataforma, url, fecha(AAAA-MM-DD), extracto, captura_url.
    El hash es el de la CAPTURA realmente descargada (si no se puede bajar, no se carga)."""
    salida = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cap_img = o.capturar(r.get("captura_url", ""))
            if not cap_img.utilizable:
                salida.append((r.get("url"), "sin_captura_descargable")); continue
            cfg = {"club": r.get("club_slug") or None, "inst": r.get("inst_slug") or None, "plataforma": r["plataforma"]}
            cid, iid = clubes.get(cfg["club"]), insts.get(cfg["inst"])
            if (cid is None) == (iid is None):
                salida.append((r["url"], "destino_inexistente")); continue
            cap = o.Captura(r["url"], 200, cap_img.contenido, cap_img.sha256)
            texto = r["extracto"]
            prop = {"plataforma": r["plataforma"], "fecha_posteo": r["fecha"], "extracto": extracto(texto),
                    "captura_url": r["captura_url"], "origen": "manual", **clasificar(texto)}
            salida.append((r["url"], o.proponer("voluntario_csv", "novedad_red", extracto(texto, 80), cap, cid, iid, prop, texto)))
    return salida


def main():
    clubes, insts = o.mapa_slugs("clubes"), o.mapa_slugs("instituciones")
    for cfg in FEEDS:
        print(procesar_feed(cfg, clubes, insts))
    if len(sys.argv) > 1:
        for url, r in cargar_csv(sys.argv[1], clubes, insts):
            print(url, "->", r)
    if not FEEDS and len(sys.argv) < 2:
        print("Sin feeds configurados ni CSV. Ver cabecera de ingesta_redes.py.")


if __name__ == "__main__":
    main()
