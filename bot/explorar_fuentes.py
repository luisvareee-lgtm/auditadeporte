"""Explorador de solo lectura: revisa sitios oficiales de municipios y provincias, respeta robots.txt
y lista los enlaces a boletín oficial, transparencia, presupuesto, concejo, compras y digesto. No escribe nada."""
import re, sys, time, json
from urllib.parse import urljoin, urlparse
import relevar_faba as r

CLAVE = re.compile(r"(?i)bolet[ií]n|transparen|presupuest|concejo|digesto|licitaci|compras|contrataci|ordenanza|decreto|rendici|rafam|ejecuci[oó]n|cuentas")
SITIOS = json.load(open(sys.argv[1], encoding="utf-8"))
for nombre, url in SITIOS.items():
    c, cab = r.capturar(url); time.sleep(2)
    final = c.url
    print(f"\n#### {nombre} | {url} -> {c.http} {c.motivo or ''}")
    if not c.utilizable:
        continue
    t = c.contenido.decode("utf-8", "ignore")
    tit = re.search(r"<title>(.*?)</title>", t, re.S | re.I)
    print("TITULO:", re.sub(r"\s+", " ", tit.group(1)).strip()[:100] if tit else "-")
    vistos = set()
    for h, txt in re.findall(r"""<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", t, re.S | re.I):
        txt = re.sub(r"<[^>]+>|\s+", " ", txt).strip()
        u = urljoin(url, h.strip())
        if CLAVE.search(u + " " + txt) and u not in vistos and not u.startswith("mailto"):
            vistos.add(u)
            print(f"   {txt[:50]:50} {u[:150]}")
        if len(vistos) >= 25:
            break
