"""Solo lectura: muestra qué responde robots.txt de un sitio y si el bot puede leer una URL. No descarga el sitio."""
import sys, urllib.request, urllib.error, urllib.robotparser
from urllib.parse import urlparse
from orquestador_bots_audita import UA

for url in sys.argv[1:]:
    p = urlparse(url); base = f"{p.scheme}://{p.netloc}"
    for ua in (UA, "Mozilla/5.0 (compatible; navegador común)"):
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=15) as r:
                txt = r.read(20000).decode("utf-8", "ignore"); print(f"\n== {base}/robots.txt [{ua[:25]}] -> {r.status}")
        except urllib.error.HTTPError as e:
            txt = ""; print(f"\n== {base}/robots.txt [{ua[:25]}] -> HTTP {e.code}")
        except Exception as e:
            txt = ""; print(f"\n== {base}/robots.txt [{ua[:25]}] -> {e}")
        if txt:
            print(txt[:1500]); rp = urllib.robotparser.RobotFileParser(); rp.parse(txt.splitlines())
            print("¿puede leer", url, "?", rp.can_fetch(UA, url))
