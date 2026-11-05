"""Diagnóstico de solo lectura: páginas oficiales de autoridades de FABA, COPAR y ENARD.
Imprime cargos y nombres institucionales tal como figuran (sin contactos) y la fecha de edición de cada página."""
import re, time
from urllib.parse import urljoin
import relevar_faba as r

PAGINAS = ["https://basquetadaptado.com.ar/autoridades/", "https://www.coparg.org.ar/nosotros/", "https://www.coparg.org.ar/",
           "https://www.enard.org.ar/", "https://enard.org.ar/institucional/", "https://www.enard.org.ar/autoridades/",
           "https://www.enard.org.ar/quienes-somos/", "https://www.coparg.org.ar/transparencia/", "https://www.enard.org.ar/transparencia/"]
CLAVE = re.compile(r"(?i)autoridad|comisi[oó]n|directorio|consejo|nosotros|institucional|transparen|memoria|balance|estatuto|rendici|estados contables")
for u in PAGINAS:
    c, cab = r.capturar(u); time.sleep(3)
    print(f"\n######## {u} -> {c.http} {c.motivo or ''}")
    if not c.utilizable:
        continue
    t = c.contenido.decode("utf-8", "ignore")
    for pat in (r'article:modified_time" content="([^"]+)', r'"dateModified":"([^"]+)', r'article:published_time" content="([^"]+)'):
        m = re.search(pat, t)
        if m: print("FECHA", pat.split('"')[0][:25], m.group(1)[:10])
    print("CABECERAS", {k: v for k, v in cab.items() if k != "Server"})
    enl = []
    for h, txt in re.findall(r"""<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", t, re.S | re.I):
        txt = re.sub(r"<[^>]+>|\s+", " ", txt).strip()
        if CLAVE.search(h + " " + txt) or h.lower().endswith(".pdf"):
            enl.append(f"{txt[:60]} -> {urljoin(u, h)}")
    print("ENLACES RELEVANTES:", *sorted(set(enl))[:40], sep="\n   ")
    ls = [r.tachar(x) for x in r.lineas(c.contenido)]
    aut = r.extraer_autoridades(ls)
    print("AUTORIDADES DETECTADAS:", [(a["cargo"], a["nombre"]) for a in aut])
    print("TEXTO (primeras líneas con cargo o año):")
    for l in ls:
        if re.search(r"(?i)presiden|secretar|tesor|vocal|director|revisor|mandato|per[ií]odo|20[12]\d", l):
            print("   |", l[:150])
