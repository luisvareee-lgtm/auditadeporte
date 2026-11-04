"""Diagnóstico de solo lectura: muestra cómo está armado el sitio de FABA (no escribe en la base)."""
import re, sys, time
from urllib.parse import urljoin
import relevar_faba as r

def hrefs(data, base):
    return [urljoin(base, h) for h in re.findall(r"""href\s*=\s*["']([^"'#]+)""", data.decode("utf-8", "ignore"), re.I)]

for sm in ("/wp-sitemap.xml", "/sitemap_index.xml", "/sitemap.xml"):
    c, _ = r.capturar(r.BASE + sm); time.sleep(2)
    print("SITEMAP", sm, c.http)
    if c.utilizable:
        try:
            _, items = r.parsear_sitemap(c.contenido)
            for loc, lm in items[:40]:
                print("  ", loc, lm)
                if loc.endswith(".xml") and any(k in loc for k in ("post", "page", "torneo", "liga", "categor", "club")):
                    c2, _ = r.capturar(loc); time.sleep(2)
                    if c2.utilizable:
                        for l2, m2 in r.parsear_sitemap(c2.contenido)[1][:60]:
                            print("     ", l2, m2)
        except Exception as e:
            print("  error", e)
        break
for slug in sys.argv[1:]:
    u = f"{r.BASE}/clubes/{slug}/"
    c, cab = r.capturar(u); time.sleep(2)
    print("\n=== FICHA", u, c.http, cab)
    t = c.contenido.decode("utf-8", "ignore")
    for m in re.findall(r'<meta[^>]+(?:article:|og:updated|modified|published)[^>]+>', t, re.I):
        print("META", m[:200])
    ext = sorted({h for h in hrefs(c.contenido, u) if "basquetadaptado.com.ar" not in h})
    print("ENLACES EXTERNOS:", *ext, sep="\n  ")
    for ln in [r.tachar(x) for x in r.lineas(c.contenido)][:80]:
        print("  |", ln[:160])
