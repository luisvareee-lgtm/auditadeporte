"""Diagnóstico de solo lectura: muestra cómo está armado el sitio de FABA (no escribe en la base).
No imprime datos de jugadores (hay menores y clasificación funcional)."""
import json, re, sys, time
import relevar_faba as r

def get(u):
    c, cab = r.capturar(u); time.sleep(2); return c, cab

for u in ("/wp-json/", "/wp-json/wp/v2/types", "/wp-json/wp/v2/categories?per_page=50&_fields=id,name,slug,count",
          "/wp-json/wp/v2/posts?per_page=30&_fields=date,modified,link,title,categories", "/feed/", "/noticias/"):
    c, _ = get(r.BASE + u)
    print("\n###", u, c.http, c.motivo)
    if c.utilizable:
        t = c.contenido.decode("utf-8", "ignore")
        if u.startswith("/wp-json/wp/v2/posts"):
            for p in json.loads(t):
                print("  ", p["date"][:10], p["title"]["rendered"][:90], p["link"])
        elif u.startswith("/wp-json/wp/v2"):
            print(t[:1500])
        elif u == "/wp-json/":
            print([x for x in json.loads(t).get("routes", {}) if "/wp/v2/" in x and "(?P" not in x][:60])
        else:
            for m in re.findall(r"<item>.*?<title>(.*?)</title>.*?<pubDate>(.*?)</pubDate>", t, re.S)[:30]:
                print("  ", m[1][:16], m[0][:90])
c, _ = get(r.LISTADO)
fichas, _ = r.urls_fichas(c.contenido, r.LISTADO)
print("\n### ANTIGÜEDAD DE FICHAS:", len(fichas))
for u in fichas:
    c, _ = get(u)
    t = c.contenido.decode("utf-8", "ignore")
    mod = (re.search(r'article:modified_time" content="([^"]+)', t) or [None, "-"])[1][:10]
    ls = r.lineas(c.contenido)
    corte = next((i for i, l in enumerate(ls) if l.lower().startswith("jugadores de selecci")), len(ls))
    ls = ls[:corte]
    plan = [l for l in ls if "control" in l.lower() or re.search(r"\b20\d\d\b", l)]
    anios = sorted({int(a) for l in plan for a in re.findall(r"\b(20[0-2]\d)\b", l)})
    redes = [f"{ls[i]}={ls[i+1][:40]}" for i, l in enumerate(ls[:-1]) if l.lower() in ("instagram", "facebook", "twitter", "youtube", "tiktok", "web", "sitio web")]
    div = [l for l in ls if re.search(r"divisi[oó]n|torneo|liga", l, re.I)][:3]
    print(f"{u.split('/clubes/')[1][:40]:41} mod={mod} años={anios[-3:] if anios else '-'} redes={redes} div={div}")
