"""AuditaDeporte - Relevador del padrón de clubes de FABA (basquetadaptado.com.ar/clubes/).

Qué hace (y qué NO hace):
  * Recorre el listado de clubes de la web oficial de FABA (con todas sus páginas) y la ficha de cada club.
  * Extrae, tal como figuran: nombre del club, localidad/provincia y autoridades (cargo + nombre).
  * Guarda la evidencia forense de cada ficha: URL, fecha y hora, HTTP, SHA-256, ETag y Last-Modified.
  * NO guarda teléfonos ni correos (se tachan antes de procesar), ni DNI/CUIL.
  * NO publica nada: todo entra a la cola de revisión privada; una persona aprueba desde el panel.
  * Respeta robots.txt, se identifica y espera entre pedidos. Si el sitio bloquea, se detiene.

Salidas:
  * salida/padron_faba_AAAAMMDD.csv y .json  (se descargan desde GitHub Actions como "artifact")
  * cola_revision (si hay credenciales y no se usa --solo-archivos):
      - autoridad_posible ......... autoridad que figura en FABA y todavía no está cargada
      - propuesta_cambio/marcar_no_vigente ... autoridad cargada que ya no figura en la ficha (verificar)
      - propuesta_cambio/solo_informativa .... club del padrón FABA que no está en AuditaDeporte,
                                               y coincidencias de nombre entre nóminas (posible homonimia)

Uso:  python relevar_faba.py [--solo-archivos] [--max-clubes N]
Secrets: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (secret key nueva sb_secret_…)."""
import argparse
import csv
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from orquestador_bots_audita import (UA, PAUSA_SEG, MAX_BYTES, Captura, _robots_permite, _norm, db,
                                     parsear_sitemap, proponer, ahora)

AGENTE = "relevador_faba"
MAX_ANTIGUEDAD_DIAS = 730        # ficha editada hace más de 2 años: sus autoridades NO se proponen (dato vencido)
CUENTAS_FABA = {"basquetadaptadofaba", "basquetfaba", "bxc3xa1squet-adaptado-faba-102847028997588"}
BASE = "https://basquetadaptado.com.ar"
LISTADO = BASE + "/clubes/"
MAX_PAGINAS_LISTADO = 40
RE_FICHA = re.compile(r"^https?://(?:www\.)?basquetadaptado\.com\.ar/clubes/([a-z0-9][a-z0-9-]*)/?$", re.I)
RE_PAGINA = re.compile(r"^https?://(?:www\.)?basquetadaptado\.com\.ar/clubes/(?:page/\d+/?|\?.*paged?=\d+.*)$", re.I)
RE_HREF = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"'#]+)["']""", re.I)

# ---------------------------------------------------------------- Datos personales que NO se guardan
RE_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_TEL = re.compile(r"(?:\+?54\s*)?(?:\(?0?\d{2,4}\)?[\s.-]*)?(?:15[\s.-]*)?\d{3,4}[\s.-]?\d{4}\b")
RE_DOC = re.compile(r"\b(?:\d{1,2}\.?\d{3}\.?\d{3}|(?:20|23|24|27)-?\d{8}-?\d)\b")


RE_ANIOS = re.compile(r"^(?:19|20)\d\d\s*[-/–]\s*(?:19|20)\d\d$")


def _tel(m):
    txt = m.group(0)
    if len(re.sub(r"\D", "", txt)) < 8 or RE_ANIOS.match(txt.strip()):   # "2021-2023" es un mandato, no un teléfono
        return txt
    return "[teléfono omitido]"


def tachar(t: str) -> str:
    t = RE_MAIL.sub("[correo omitido]", t or "")
    t = RE_DOC.sub("[nro omitido]", t)
    return RE_TEL.sub(_tel, t)


# ---------------------------------------------------------------- Captura con cabeceras (integridad forense)
def capturar(url: str, timeout: int = 25):
    """Como orquestador.capturar, pero además devuelve ETag / Last-Modified / Content-Type."""
    if not _robots_permite(url):
        return Captura(url, 0, motivo="robots_no_permite"), {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-AR,es"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
            cab = {k: r.headers.get(k) for k in ("ETag", "Last-Modified", "Content-Type", "Server") if r.headers.get(k)}
            if len(data) > MAX_BYTES:
                return Captura(url, r.getcode(), motivo="archivo_demasiado_grande"), cab
            return Captura(url, r.getcode(), data, hashlib.sha256(data).hexdigest()), cab
    except urllib.error.HTTPError as e:
        return Captura(url, e.code, motivo=f"http_{e.code}"), {}
    except Exception as exc:
        return Captura(url, 0, motivo=f"red:{exc}"), {}


# ---------------------------------------------------------------- HTML -> líneas de texto
RE_FUERA = re.compile(r"<(script|style|noscript|svg|nav|footer|header|form)\b[^>]*>.*?</\1>", re.S | re.I)
RE_BLOQUE = re.compile(r"<\s*/?\s*(br|p|div|li|ul|ol|h[1-6]|tr|td|th|dt|dd|table|section|article|strong|b)\b[^>]*>", re.I)
RE_ETIQ = re.compile(r"<[^>]+>")


def lineas(data: bytes) -> list:
    t = data.decode("utf-8", "ignore")
    m = re.search(r"<(main|article)\b[^>]*>(.*)</\1>", t, re.S | re.I)   # priorizar el contenido principal
    t = m.group(2) if m else t
    t = RE_FUERA.sub(" ", t)
    t = RE_BLOQUE.sub("\n", t)
    t = html.unescape(RE_ETIQ.sub(" ", t)).replace("\xa0", " ")
    out = []
    for ln in t.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip(" \t|•·")
        if not ln:
            continue
        # Desde acá la ficha lista jugadores: hay menores de edad y clasificación funcional (dato de salud). No se procesa.
        if re.match(r"(?i)^(jugador(a|es|as)? de selecci|plantel|jugadores)\b", ln):
            break
        out.append(ln)
    return out


def titulo_pagina(data: bytes) -> str:
    t = data.decode("utf-8", "ignore")
    for pat in (r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', r"<h1\b[^>]*>(.*?)</h1>", r"<title>(.*?)</title>"):
        m = re.search(pat, t, re.S | re.I)
        if m:
            s = re.sub(r"\s+", " ", html.unescape(RE_ETIQ.sub(" ", m.group(1)))).strip()
            s = re.split(r"\s+[|–—-]\s+(?:FABA|Federaci[oó]n|B[aá]squet Adaptado)", s, flags=re.I)[0].strip()
            if s:
                return s[:200]
    return ""


# ---------------------------------------------------------------- Autoridades
CARGO = (r"(?:vice\s*-?\s*presidente(?:\s*(?:1|2|primero|segundo)[°º]?)?|presidente|"
         r"pro\s*-?\s*secretari[oa]|secretari[oa](?:\s+(?:general|de\s+actas|deportiv[oa]))?|"
         r"pro\s*-?\s*tesorer[oa]|tesorer[oa]|"
         r"vocal(?:es)?(?:\s+(?:titular|suplente)(?:es)?)?(?:\s*\d+\s*[°º]?)?|"
         r"revisor(?:a|es)?\s+de\s+cuentas(?:\s+(?:titular|suplente))?|"
         r"delegad[oa](?:\s+(?:titular|suplente))?(?:\s+ante\s+(?:la\s+)?faba)?|"
         r"coordinador(?:a)?(?:\s+deportiv[oa])?|director(?:a)?\s+t[eé]cnic[oa]|entrenador(?:a)?|"
         r"ayudante\s+de\s+campo|asistente\s+t[eé]cnic[oa])")
RE_CARGO_SOLO = re.compile(rf"^{CARGO}\s*:?$", re.I)
RE_CARGO_NOMBRE = re.compile(rf"^(?P<cargo>{CARGO})\s*[:\-–—]\s*(?P<nombre>.+)$", re.I)
RE_NOMBRE_CARGO = re.compile(rf"^(?P<nombre>[^:()\-–—]+?)\s*(?:[:\-–—,]|\()\s*(?P<cargo>{CARGO})\)?\.?$", re.I)
RE_PREFIJO = re.compile(r"^(?:sr|sra|srta|dr|dra|lic|prof|ing|cdor|cdora)\.?\s+", re.I)
PALABRA = re.compile(r"^(?:[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü'’]+(?:-[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü'’]+)?|[A-ZÁÉÍÓÚÑÜ]{2,}|[A-ZÁÉÍÓÚÑ]\.|de|del|la|las|los|y|da|di|van|von)$")


def nombre_valido(s: str):
    """Devuelve el nombre limpio o None. Solo acepta nombres de persona escritos como tales (2 a 6 palabras)."""
    s = RE_PREFIJO.sub("", re.sub(r"\s+", " ", (s or "")).strip(" .,;:"))
    if not 5 <= len(s) <= 80 or re.search(r"[\d@/\\[\]{}<>|=_]", s) or "omitido" in s:
        return None
    pal = s.split(" ")
    if not 2 <= len(pal) <= 6 or not all(PALABRA.match(p) for p in pal):
        return None
    if sum(p[0].isupper() for p in pal) < 2:
        return None
    if RE_CARGO_SOLO.match(s) or _norm(s) in ("comision directiva", "cuerpo tecnico", "datos del club"):
        return None
    if s.isupper():                                   # "JUAN PEREZ" -> "Juan Perez"
        s = " ".join(p if len(p) <= 2 and p.endswith(".") else p.capitalize() for p in pal)
    return s


def cargo_normalizado(c: str) -> str:
    c = re.sub(r"\s+", " ", c).strip(" :")
    c = re.sub(r"(?i)^vice\s*-?\s*", "Vice", c)
    c = re.sub(r"(?i)^pro\s*-?\s*", "Pro", c)
    return c[:1].upper() + c[1:].lower().replace("faba", "FABA")


def extraer_autoridades(ls: list) -> list:
    """[{cargo, nombre, linea}] con el texto ya tachado. Conservador: si duda, no extrae."""
    res, vistos = [], set()

    def agregar(cargo, nombre, linea):
        nombre = re.split(r"\s+(?:tel\.?|tel[eé]fono|cel\.?|celular|whatsapp|mail|e-?mail|correo|contacto)\b|\s*\[", nombre, flags=re.I)[0]
        n = nombre_valido(nombre)
        if not n:
            return
        clave = (_norm(cargo_normalizado(cargo)), _norm(n))
        if clave not in vistos:
            vistos.add(clave)
            res.append({"cargo": cargo_normalizado(cargo), "nombre": n, "linea": linea[:200]})

    for i, ln in enumerate(ls):
        m = RE_CARGO_NOMBRE.match(ln)
        if m:
            agregar(m["cargo"], m["nombre"], ln); continue
        m = RE_NOMBRE_CARGO.match(ln)
        if m:
            agregar(m["cargo"], m["nombre"], ln); continue
        if RE_CARGO_SOLO.match(ln) and i + 1 < len(ls):            # "Presidente" / "Juan Pérez" en líneas separadas
            agregar(ln.rstrip(" :"), ls[i + 1], f"{ln} {ls[i + 1]}")
    return res


ETIQUETAS = {"localidad": r"(?:localidad|ciudad|partido)", "provincia": r"provincia", "sede": r"(?:sede|direcci[oó]n|domicilio|estadio|cancha)",
             "division": r"(?:divisi[oó]n|categor[ií]a)"}


def extraer_datos(ls: list) -> dict:
    out = {}
    for clave, et in ETIQUETAS.items():
        for i, ln in enumerate(ls):
            m = re.match(rf"^{et}\s*:\s*(.+)$", ln, re.I)
            v = m.group(1) if m else (ls[i + 1] if re.match(rf"^{et}\s*:?$", ln, re.I) and i + 1 < len(ls) else None)
            if v and len(v) <= 150:
                out[clave] = v.strip(); break
    return out


def fecha_ficha(data: bytes):
    """Última edición declarada por la propia página (article:modified_time). La cabecera Last-Modified no sirve:
    el servidor la regenera aunque el contenido no cambie."""
    m = re.search(r'article:modified_time["\']\s+content=["\'](\d{4}-\d\d-\d\d)', data.decode("utf-8", "ignore"))
    return m.group(1) if m else None


def anios_planillas(ls: list) -> list:
    return sorted({int(a) for l in ls if "control" in l.lower() for a in re.findall(r"\b(20[0-4]\d)\b", l)})


RE_IG = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def _ig(v: str):
    v = (v or "").strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9._]{1,30})", v)
    h = m.group(1) if m else v.strip("@/ ").split("?")[0]
    return h if RE_IG.match(h) and h.lower() not in CUENTAS_FABA and not h.replace(".", "").isdigit() else None


def _fb(v: str):
    v = (v or "").strip()
    m = re.search(r"facebook\.com/([^\s?#]+)", v)
    if m:
        h = m.group(1).strip("/")
    elif re.match(r"^/?[A-Za-z0-9.\-]{3,80}/?$", v):
        h = v.strip("/")
    else:
        return None
    if "faba" in h.lower() or re.match(r"(?i)^(sharer|share|dialog|plugins|tr|login|l\.php|groups/?$)", h):
        return None                                  # cuenta de FABA o botón de "compartir", no la del club
    return f"https://www.facebook.com/{h}"


def extraer_redes(ls: list, data: bytes) -> dict:
    """Redes que la ficha publica para el club (no las de FABA). 'texto' guarda lo escrito cuando no es un enlace usable."""
    out, texto = {}, {}
    for i, l in enumerate(ls[:-1]):
        k = _norm(l).strip(" :")
        v = ls[i + 1]
        if k == "instagram":
            texto["instagram"] = v[:80]
            if _ig(v):
                out.setdefault("instagram", _ig(v))
        elif k == "facebook":
            texto["facebook"] = v[:80]
            if _fb(v):
                out.setdefault("facebook", _fb(v))
        elif k in ("sitio web", "web", "pagina web") and re.match(r"^https?://", v):
            out.setdefault("web", v.split()[0][:200])
    for h in RE_HREF.findall(data.decode("utf-8", "ignore")):
        if "instagram.com/" in h and _ig(h):
            out.setdefault("instagram", _ig(h))
        elif "facebook.com/" in h and _fb(h):
            out.setdefault("facebook", _fb(h))
    if texto:
        out["texto_publicado"] = texto
    return out


# ---------------------------------------------------------------- Listado de clubes
def urls_fichas(html_bytes: bytes, base: str):
    fichas, paginas = [], []
    for href in RE_HREF.findall(html_bytes.decode("utf-8", "ignore")):
        u = urljoin(base, html.unescape(href.strip()))
        m = RE_FICHA.match(u)
        if m and m.group(1).lower() not in ("page", "feed"):
            u = u.rstrip("/") + "/"
            if u not in fichas:
                fichas.append(u)
        elif RE_PAGINA.match(u) and u not in paginas:
            paginas.append(u)
    return fichas, paginas


LISTADO_CAP = [None]


def recorrer_listado(registro: list):
    pendientes, vistas, fichas = [LISTADO], set(), []
    while pendientes and len(vistas) < MAX_PAGINAS_LISTADO:
        u = pendientes.pop(0)
        if u in vistas:
            continue
        vistas.add(u)
        cap, _ = capturar(u)
        time.sleep(PAUSA_SEG)
        registro.append({"url": u, "http": cap.http, "motivo": cap.motivo})
        if cap.bloqueada:
            raise SystemExit(f"El sitio no permite el acceso ({cap.http or cap.motivo}) en {u}. Se respeta y se detiene.")
        if not cap.utilizable:
            continue
        if u == LISTADO:
            LISTADO_CAP[0] = cap
        f, p = urls_fichas(cap.contenido, u)
        fichas += [x for x in f if x not in fichas]
        pendientes += [x for x in p if x not in vistas and x not in pendientes]
    if not fichas:                                       # plan B: sitemap del sitio
        for sm in (BASE + "/sitemap_index.xml", BASE + "/wp-sitemap.xml", BASE + "/sitemap.xml"):
            cap, _ = capturar(sm)
            time.sleep(PAUSA_SEG)
            if not cap.utilizable:
                continue
            try:
                es_indice, items = parsear_sitemap(cap.contenido)
                if es_indice:
                    hijos = [loc for loc, _ in items if "club" in loc.lower()][:5]
                    items = []
                    for h in hijos:
                        c2, _ = capturar(h); time.sleep(PAUSA_SEG)
                        if c2.utilizable:
                            items += parsear_sitemap(c2.contenido)[1]
            except Exception:
                continue
            fichas = [loc.rstrip("/") + "/" for loc, _ in items if RE_FICHA.match(loc)]
            if fichas:
                break
    return fichas


# ---------------------------------------------------------------- Cruce con la base
VACIAS = {"club", "asociacion", "civil", "deportiva", "deportivo", "deportes", "deporte", "basquet", "adaptado", "sobre",
          "silla", "sillas", "ruedas", "del", "los", "las", "municipalidad", "municipal", "fundacion", "centro", "social",
          "cultural", "sede", "argentina", "atletico", "personas", "para"}


def _tokens(s):
    """Palabras distintivas. Las siglas escritas con guiones o puntos (c-ri-pa-l, s.i.c.a) se vuelven a unir (cripal, sica)."""
    crudos = [t for t in re.split(r"[^a-z0-9]+", _norm(s)) if t]
    out, sigla = [], []
    for t in crudos + [""]:
        if t and len(t) <= 2 and not t.isdigit():
            sigla.append(t); continue
        if len(sigla) >= 3:
            out.append("".join(sigla))
        sigla = []
        if t:
            out.append(t)
    return {t for t in out if (len(t) > 2 or t.isdigit()) and t not in VACIAS}


def emparejar(slug_faba: str, nombre: str, clubes: list):
    """Devuelve (club, 'slug'|'nombre'|'contenido'|'aproximada', puntaje) o (None, None, 0).
    Si dos clubes empatan, no elige ninguno: lo resuelve una persona."""
    for c in clubes:
        if c["slug"] == slug_faba:
            return c, "slug", 1.0
    for c in clubes:
        if _norm(c["nombre"]) == _norm(nombre):
            return c, "nombre", 1.0
    a = _tokens(nombre) | _tokens(slug_faba.replace("-", " "))
    contenidos, mejor, pm, empate = [], None, 0.0, False
    for c in clubes:
        b = _tokens(c["nombre"]) | _tokens(c["slug"].replace("-", " "))
        if not (a and b):
            continue
        if b <= a:              # nuestro nombre está contenido en el de FABA: "prodea" ⊂ "prodea las aguilas".
                                # Al revés no: "SICA / Poeta Lugones" tiene más datos que "Club Poeta Lugones".
            contenidos.append(c)
        p = len(a & b) / len(a | b)
        if p > pm:
            mejor, pm, empate = c, p, False
        elif p == pm and p > 0:
            empate = True
    if len(contenidos) == 1:
        return contenidos[0], "contenido", 1.0
    if pm >= 0.75 and not empate and not contenidos:
        return mejor, "aproximada", round(pm, 2)
    return None, None, 0


def leer(tabla, cols):
    try:
        return db().table(tabla).select(cols).execute().data or []
    except Exception as exc:
        print(f"aviso: no se pudo leer {tabla}: {exc}")
        return []


# ---------------------------------------------------------------- Ciclo
def relevar(max_clubes=None):
    registro = []
    fichas = recorrer_listado(registro)
    if max_clubes:
        fichas = fichas[:max_clubes]
    print(f"fichas encontradas: {len(fichas)}")
    clubes = []
    for u in fichas:
        cap, cab = capturar(u)
        time.sleep(PAUSA_SEG)
        fila = {"url": u, "slug_faba": RE_FICHA.match(u).group(1), "http": cap.http, "sha256": cap.sha256,
                "etag": cab.get("ETag"), "last_modified": cab.get("Last-Modified"), "content_type": cab.get("Content-Type"),
                "relevado_en": ahora().isoformat(timespec="seconds"), "motivo": cap.motivo, "_cap": cap}
        if cap.bloqueada:
            fila["resultado"] = "bloqueada"; clubes.append(fila)
            print(f"bloqueo en {u}: se detiene el relevamiento"); break
        if cap.utilizable:
            ls = [tachar(x) for x in lineas(cap.contenido)]
            f = fecha_ficha(cap.contenido)
            dias = (ahora().date() - datetime.strptime(f, "%Y-%m-%d").date()).days if f else None
            fila.update(nombre=titulo_pagina(cap.contenido) or fila["slug_faba"], datos=extraer_datos(ls),
                        autoridades=extraer_autoridades(ls), redes=extraer_redes(ls, cap.contenido),
                        fecha_ficha=f, antiguedad_dias=dias, anios_planillas=anios_planillas(ls),
                        vigente=dias is not None and dias <= MAX_ANTIGUEDAD_DIAS, resultado="ok",
                        legibilidad="texto_nativo" if sum(map(len, ls)) >= 200 else "sin_texto_legible")
        else:
            fila["resultado"] = "error"
        clubes.append(fila)
    return clubes, registro


def guardar_archivos(clubes, carpeta="salida"):
    Path(carpeta).mkdir(exist_ok=True)
    hoy = datetime.now(timezone.utc).strftime("%Y%m%d")
    pub = [{k: v for k, v in c.items() if not k.startswith("_")} for c in clubes]
    Path(carpeta, f"padron_faba_{hoy}.json").write_text(json.dumps(pub, ensure_ascii=False, indent=1), encoding="utf-8")
    campos = ["club_faba", "url_ficha", "slug_faba", "club_auditadeporte", "coincidencia", "localidad", "provincia",
              "cargo", "nombre", "fecha_ficha", "antiguedad_dias", "dato_vigente", "instagram", "facebook", "web",
              "relevado_en", "http", "sha256", "etag", "last_modified", "legibilidad"]
    with open(Path(carpeta, f"padron_faba_{hoy}.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        for c in pub:
            base = {"club_faba": c.get("nombre"), "url_ficha": c["url"], "slug_faba": c["slug_faba"],
                    "club_auditadeporte": c.get("club_slug"), "coincidencia": c.get("coincidencia"),
                    "localidad": (c.get("datos") or {}).get("localidad"), "provincia": (c.get("datos") or {}).get("provincia"),
                    "relevado_en": c["relevado_en"], "http": c["http"], "sha256": c["sha256"], "etag": c.get("etag"),
                    "last_modified": c.get("last_modified"), "legibilidad": c.get("legibilidad"),
                    "fecha_ficha": c.get("fecha_ficha"), "antiguedad_dias": c.get("antiguedad_dias"),
                    "dato_vigente": "si" if c.get("vigente") else "no",
                    **{k: (c.get("redes") or {}).get(k) for k in ("instagram", "facebook", "web")}}
            for a in c.get("autoridades") or [{}]:
                w.writerow({**base, "cargo": a.get("cargo"), "nombre": a.get("nombre")})
    return carpeta


def descartar_pendientes(club_id, c) -> int:
    """Retira las sugerencias de autoridades que ESTE agente dejó pendientes para un club cuya ficha está vencida.
    No toca nada aprobado ni nada propuesto por otros agentes. Queda registrado quién y por qué."""
    pend = db().table("cola_revision").select("id").eq("agente", AGENTE).eq("tipo", "autoridad_posible") \
        .eq("estado", "pendiente").eq("club_id", club_id).execute().data or []
    for p in pend:
        db().table("cola_revision").update({
            "estado": "rechazada", "motivo_codigo": "desactualizado", "revisada_por": f"{AGENTE} (automático)",
            "revisada_en": ahora().isoformat(),
            "nota_revision": f"La ficha FABA se editó por última vez el {c.get('fecha_ficha') or '(sin fecha)'}: "
                             f"más de {MAX_ANTIGUEDAD_DIAS // 365} años. No sirve como fuente de autoridades actuales."}).eq("id", p["id"]).execute()
    return len(pend)


def retirar_redes_previas(club_id, nuevas: dict) -> int:
    """Si este agente dejó pendiente una propuesta de redes distinta de la actual (p. ej. un error ya corregido), la retira."""
    pend = db().table("cola_revision").select("id,propuesta").eq("agente", AGENTE).eq("tipo", "propuesta_cambio") \
        .eq("estado", "pendiente").eq("club_id", club_id).execute().data or []
    n = 0
    for p in pend:
        pr = p.get("propuesta") or {}
        if pr.get("accion") == "actualizar_redes_club" and pr.get("parametros") != nuevas:
            db().table("cola_revision").update({
                "estado": "rechazada", "motivo_codigo": "otro", "revisada_por": f"{AGENTE} (automático)",
                "revisada_en": ahora().isoformat(),
                "nota_revision": "Retirada por el agente: la propuesta tenía un enlace equivocado y fue reemplazada."}).eq("id", p["id"]).execute()
            n += 1
    return n


def _cap_ancla(cap: Captura, ancla: str) -> Captura:
    """Un ítem de cola por autoridad: misma página y mismo hash, con un ancla que lo distingue."""
    return Captura(f"{cap.url}#{ancla}", cap.http, b"", cap.sha256)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", _norm(s)).strip("-")[:60]


def proponer_en_cola(clubes):
    lista_clubes = leer("clubes", "id,slug,nombre,instagram,facebook,web")
    autoridades = leer("autoridades", "id,club_id,institucion_id,nombre,cargo,vigente")
    insts = {i["slug"]: i for i in leer("instituciones", "id,slug,sigla")}
    faba_id = (insts.get("faba") or {}).get("id")
    cont = {"autoridad_posible": 0, "no_figura": 0, "club_no_registrado": 0, "cruce": 0, "redes": 0,
            "ficha_desactualizada": 0, "descartadas_por_antiguedad": 0, "duplicado": 0, "bloqueado_legal": 0}

    def contar(r, clave):
        cont[clave if r == "nuevo" else r] = cont.get(clave if r == "nuevo" else r, 0) + 1

    hoy = datetime.now(timezone.utc).date().isoformat()
    por_nombre = {}                                         # para el cruce de nóminas: nombre -> [(origen, entidad, datos)]
    for a in autoridades:
        if a.get("vigente"):
            por_nombre.setdefault(_norm(a["nombre"]), []).append(("base", a.get("club_id") or a.get("institucion_id"), a))

    for c in clubes:
        if c.get("resultado") != "ok":
            continue
        cap = c["_cap"]
        club, como, puntaje = emparejar(c["slug_faba"], c["nombre"], lista_clubes)
        c["club_slug"], c["coincidencia"] = (club or {}).get("slug"), (f"{como} ({puntaje})" if club else "sin_coincidencia")
        entidad = club["id"] if club else "faba:" + c["slug_faba"]
        if not c.get("vigente"):
            cont["ficha_desactualizada"] += 1
            if club:
                cont["descartadas_por_antiguedad"] += descartar_pendientes(club["id"], c)
        for a in (c["autoridades"] if c.get("vigente") else []):
            por_nombre.setdefault(_norm(a["nombre"]), []).append(("faba", entidad, {**a, "club": c["nombre"], "url": c["url"]}))

        if not club:
            if faba_id:
                r = proponer(AGENTE, "propuesta_cambio", f"Club del padrón FABA no registrado en AuditaDeporte: {c['nombre']}",
                             cap, inst_id=faba_id,
                             propuesta={"accion": "solo_informativa", "fuente": "padron_faba",
                                        "parametros": {"nombre": c["nombre"], "url_ficha": c["url"], "datos": c["datos"],
                                                       "redes": c.get("redes"), "fecha_ficha": c.get("fecha_ficha"),
                                                       "autoridades": [{k: a[k] for k in ("cargo", "nombre")} for a in c["autoridades"]],
                                                       "fecha_relevamiento": hoy}},
                             texto_para_filtro=c["nombre"])
                contar(r, "club_no_registrado")
            continue

        redes = {k: v for k, v in (c.get("redes") or {}).items() if k in ("instagram", "facebook", "web")}
        nuevas = {k: v for k, v in redes.items() if (club.get(k) or "").rstrip("/").lower() != v.rstrip("/").lower()}
        cont["redes_retiradas"] = cont.get("redes_retiradas", 0) + retirar_redes_previas(club["id"], nuevas)
        if nuevas:
            r = proponer(AGENTE, "propuesta_cambio", f"{club['nombre']}: redes publicadas en la ficha FABA ({', '.join(nuevas)})",
                         _cap_ancla(cap, "redes"), club_id=club["id"],
                         propuesta={"accion": "actualizar_redes_club", "parametros": nuevas, "fuente": "padron_faba",
                                    "url_ficha": c["url"], "fecha_posteo": c.get("fecha_ficha"),
                                    "actuales": {k: club.get(k) for k in nuevas},
                                    "nota": "Abrí cada cuenta y confirmá que es del club y que sigue activa antes de aprobar."},
                         texto_para_filtro=" ".join(nuevas.values()))
            contar(r, "redes")
        if not c.get("vigente"):
            continue
        cargadas = [a for a in autoridades if a.get("club_id") == club["id"]]
        claves_base = {(_norm(a["nombre"]), _norm(a["cargo"])) for a in cargadas}
        for a in c["autoridades"]:
            if (_norm(a["nombre"]), _norm(a["cargo"])) in claves_base:
                continue
            r = proponer(AGENTE, "autoridad_posible", f"{club['nombre']}: {a['cargo']} — {a['nombre']} (padrón FABA)",
                         _cap_ancla(cap, "autoridad-" + _slug(a["cargo"] + "-" + a["nombre"])), club_id=club["id"],
                         propuesta={"nombre": a["nombre"], "cargo": a["cargo"], "fecha_fuente": hoy,
                                    "linea_fuente": a["linea"], "fuente": "padron_faba", "url_ficha": c["url"],
                                    "etag": c.get("etag"), "last_modified": c.get("last_modified")},
                         texto_para_filtro=f"{a['cargo']} {a['nombre']}")
            contar(r, "autoridad_posible")
        if c["autoridades"]:                                  # solo si la ficha trae nómina: si no, no se infiere nada
            en_faba = {_norm(a["nombre"]) for a in c["autoridades"]}
            for a in cargadas:
                if a.get("vigente") and _norm(a["nombre"]) not in en_faba:
                    r = proponer(AGENTE, "propuesta_cambio",
                                 f"Verificar: {a['cargo']} {a['nombre']} no figura en la ficha FABA de {club['nombre']} ({hoy})",
                                 _cap_ancla(cap, "no-figura-" + a["id"]), club_id=club["id"],
                                 propuesta={"accion": "marcar_no_vigente", "parametros": {"autoridad_id": a["id"]},
                                            "fuente": "padron_faba", "url_ficha": c["url"],
                                            "nota": "Aprobar solo si confirmás en la fuente que la persona ya no ocupa el cargo."},
                                 texto_para_filtro=a["nombre"])
                    contar(r, "no_figura")

    # Cruce de nóminas: mismo nombre en más de una entidad. Es una coincidencia de texto, no una conclusión.
    if faba_id:
        for clave, apar in por_nombre.items():
            entidades = {e for _, e, _ in apar}
            faba_apar = [x for x in apar if x[0] == "faba"]
            if len(entidades) < 2 or not faba_apar:
                continue
            cap = next(c["_cap"] for c in clubes if c["url"] == faba_apar[0][2]["url"])
            nombre = faba_apar[0][2]["nombre"]
            detalle = [{"origen": o, "cargo": x["cargo"], "entidad": x.get("club") or e, "url": x.get("url")} for o, e, x in apar]
            r = proponer(AGENTE, "propuesta_cambio", f"Coincidencia de nombre en nóminas: {nombre} figura en {len(entidades)} entidades",
                         _cap_ancla(cap, "cruce-" + _slug(nombre)), inst_id=faba_id,
                         propuesta={"accion": "solo_informativa", "fuente": "padron_faba",
                                    "parametros": {"nombre": nombre, "apariciones": detalle,
                                                   "nota": "Coincidencia de texto: puede tratarse de homónimos. Verificar en registros "
                                                           "oficiales (DPPJ/IGJ/IPJ) antes de cualquier uso."}},
                         texto_para_filtro=nombre)
            contar(r, "cruce")

    # El estado del padrón en sí es un hallazgo de transparencia activa (dato objetivo, sin calificativos).
    leidas = [c for c in clubes if c.get("resultado") == "ok"]
    vencidas = [c for c in leidas if not c.get("vigente")]
    if faba_id and vencidas and LISTADO_CAP[0]:
        ult = max((c.get("fecha_ficha") or "") for c in leidas) or "(sin fecha)"
        r = proponer(AGENTE, "propuesta_cambio",
                     f"Padrón web de FABA: {len(vencidas)} de {len(leidas)} fichas de clubes sin editar hace más de "
                     f"{MAX_ANTIGUEDAD_DIAS // 365} años (edición más reciente: {ult})",
                     _cap_ancla(LISTADO_CAP[0], "antiguedad-" + ult), inst_id=faba_id,
                     propuesta={"accion": "solo_informativa", "fuente": "padron_faba",
                                "parametros": {"fichas_leidas": len(leidas), "fichas_vencidas": len(vencidas),
                                               "edicion_mas_reciente": ult, "fecha_corte": hoy,
                                               "nota": "Insumo para un pedido de acceso a la información (Ley 27.275, art. 32: "
                                                       "transparencia activa) sobre el padrón vigente de clubes y autoridades."}},
                     texto_para_filtro="padron")
        contar(r, "padron")
    return cont


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-archivos", action="store_true", help="no escribe en la base, solo genera CSV/JSON")
    ap.add_argument("--max-clubes", type=int, default=None)
    args = ap.parse_args()
    usar_base = not args.solo_archivos and os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    ej_id = None
    if usar_base:
        ej = db().table("agente_ejecuciones").insert({"agente": AGENTE, "objetivos": 1}).execute()
        ej_id = ej.data[0]["id"] if ej.data else None
    try:
        clubes, registro = relevar(args.max_clubes)
    except SystemExit as fin:
        if ej_id:
            db().table("agente_ejecuciones").update({"fin": ahora().isoformat(), "ok": 0, "bloqueados": 1, "errores": 0,
                                                     "detalle": {"motivo": str(fin)}}).eq("id", ej_id).execute()
        raise
    cont = proponer_en_cola(clubes) if usar_base else {}
    carpeta = guardar_archivos(clubes)
    ok = sum(c.get("resultado") == "ok" for c in clubes)
    n_aut = sum(len(c.get("autoridades") or []) for c in clubes)
    resumen = {"fichas": len(clubes), "ok": ok, "autoridades_extraidas": n_aut, "cola": cont, "listado": registro[:50]}
    if ej_id:
        db().table("agente_ejecuciones").update({"fin": ahora().isoformat(), "ok": ok,
                                                 "bloqueados": sum(c.get("resultado") == "bloqueada" for c in clubes),
                                                 "errores": sum(c.get("resultado") == "error" for c in clubes),
                                                 "detalle": resumen}).eq("id", ej_id).execute()
    print(f"fichas={len(clubes)} leidas={ok} autoridades={n_aut} cola={cont} archivos en {carpeta}/")
    print("--- resumen por club (slug FABA -> club AuditaDeporte | localidad | autoridades) ---")
    for c in clubes:
        aut = "; ".join(f"{a['cargo']}: {a['nombre']}" for a in c.get("autoridades") or []) or "(sin nómina reconocida)"
        rd = {k: v for k, v in (c.get("redes") or {}).items() if k != "texto_publicado"}
        print(f"{c['slug_faba']} -> {c.get('club_slug') or 'SIN COINCIDENCIA'} | ficha {c.get('fecha_ficha') or '?'}"
              f"{'' if c.get('vigente') else ' (VENCIDA)'} | {aut} | redes {rd or '-'}")
    sin = [c["url"] for c in clubes if c.get("resultado") == "ok" and not c.get("autoridades")]
    if sin:
        print(f"{len(sin)} ficha(s) sin nómina reconocible (revisarlas a mano): " + ", ".join(sin[:10]))


if __name__ == "__main__":
    main()
