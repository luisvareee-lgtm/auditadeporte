"""Diagnóstico de solo lectura del sitio de FABA (no escribe en la base, no imprime datos de jugadores)."""
import re, time
from urllib.parse import urljoin
import relevar_faba as r
for u in (r.BASE + "/noticias/", r.BASE + "/noticias/page/2/", r.BASE + "/"):
    c, _ = r.capturar(u); time.sleep(2)
    print("\n###", u, c.http)
    if not c.utilizable: continue
    t = c.contenido.decode("utf-8", "ignore")
    links = []
    for h in re.findall(r"""href\s*=\s*["']([^"'#]+)""", t, re.I):
        h = urljoin(u, h)
        if "basquetadaptado.com.ar" in h and h not in links and not re.search(r"/(clubes|wp-|feed|tag)/|\.(css|js|png|jpg)", h):
            links.append(h)
    print("ENLACES:", *links[:70], sep="\n  ")
    ls = r.lineas(c.contenido)
    print("FECHAS:", [l for l in ls if re.search(r"\b\d{1,2} \w+, 20\d\d\b|20\d\d-\d\d-\d\d", l)][:25])
