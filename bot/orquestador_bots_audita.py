"""AuditaDeporte - rastreador de documentos públicos v6.0
REGLA DE ORO: los agentes PROPONEN (tabla privada cola_revision); una persona APRUEBA desde el panel.
Ningún agente escribe en tablas públicas, ni afirma "no encontrado", ni evade bloqueos.
Novedades v6:
  * Lee las fuentes de la tabla fuentes_monitoreadas (se cargan desde el panel, sin tocar código).
  * Descubre páginas nuevas por sitemap.xml (con filtro por patrón y por dominio).
  * Detecta cambios por hash: documento_nuevo vs documento_cambio (guarda el hash anterior).
  * Extrae texto de PDF/HTML: expedientes, CUIT de entidades y marca requiere_ocr_o_revision_humana.
  * Registra el estado de cada fuente (activa / caida / bloqueada_robots) para medir cobertura.
Secrets (GitHub Actions): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (secret key). Nunca en el sitio ni en el repo."""
import gzip
import hashlib
import html
import io
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

UA = "AuditaDeporteBot/6.0 (observatorio civico sin fines de lucro; contacto en el sitio)"
PAUSA_SEG = 2.0                 # cortesía entre pedidos
MAX_BYTES = 25 * 1024 * 1024    # no se descargan archivos más grandes
MAX_FUENTES_POR_CICLO = 40
MAX_CAPTURAS_POR_CICLO = 150    # tope total para no exceder el tiempo del workflow
MAX_DESCUBIERTAS_POR_FUENTE = 15
MAX_PAGINAS_PDF = 40
_cliente = None


def db():
    global _cliente
    if _cliente is None:
        from supa import Cliente
        _cliente = Cliente(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    return _cliente


def ahora():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- Captura honesta
@dataclass
class Captura:
    url: str
    http: int                 # 0 = error de red; 401/403/429 = bloqueo (se respeta)
    contenido: bytes = b""
    sha256: Optional[str] = None
    motivo: str = ""

    @property
    def bloqueada(self):
        return self.http in (401, 403, 429) or self.motivo == "robots_no_permite"

    @property
    def utilizable(self):
        return self.http == 200 and bool(self.contenido) and bool(self.sha256)


def _robots_permite(url: str) -> bool:
    p = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch(UA, url)
    except Exception:
        return True  # si robots.txt no responde, seguimos con ritmo cortés


def capturar(url: str, timeout: int = 25) -> Captura:
    """Se identifica, respeta robots.txt, no rota identidades, no reintenta bloqueos y no hashea descargas incompletas."""
    if not (url or "").lower().startswith(("http://", "https://")):
        return Captura(url, 0, motivo="url_invalida")
    if not _robots_permite(url):
        return Captura(url, 0, motivo="robots_no_permite")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return Captura(url, r.getcode(), motivo="archivo_demasiado_grande")
            return Captura(url, r.getcode(), data, hashlib.sha256(data).hexdigest())
    except urllib.error.HTTPError as e:
        return Captura(url, e.code, motivo=f"http_{e.code}")
    except Exception as exc:
        return Captura(url, 0, motivo=f"red:{exc}")


# ---------------------------------------------------------------- Agente Jurídico (pre-filtro)
def _norm(t: str) -> str:
    return unicodedata.normalize("NFD", (t or "").lower()).encode("ascii", "ignore").decode()


TERMINOS_VETADOS = ["corrupcion", "corrupto", "robo", "robaron", "estafa", "malversacion", "delito",
                    "fraude", "ilegal", "ladron", "coima", "desvio de fondos", "mafia"]
RE_DNI = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}\b")
RE_CUIL = re.compile(r"\b(20|23|24|27|30|33)-?\d{8}-?\d\b")


def pre_filtro_juridico(texto: str, url: str) -> list:
    """Devuelve motivos de bloqueo ([] = puede pasar a revisión humana).
    NO es una validación legal: solo evita que entren a la cola calificativos, imputaciones o datos personales."""
    motivos, t = [], _norm(texto or "")
    for term in TERMINOS_VETADOS:
        if re.search(rf"\b{re.escape(term)}\b", t):
            motivos.append(f"termino_vetado:{term}")
    if RE_DNI.search(texto or "") or RE_CUIL.search(texto or ""):
        motivos.append("posible_dato_personal(DNI/CUIL)")
    if not (url or "").lower().startswith(("http://", "https://")):
        motivos.append("sin_fuente_verificable")
    return motivos


# ---------------------------------------------------------------- Agente Analista documental
RE_EXP_GDE = re.compile(r"\bEX-\d{4}-\d{5,9}-\s*-?\s*[A-Z]{2,6}(?:-[A-Z0-9#]{2,15})*")
RE_EXP_LOCAL = re.compile(r"\b(?:expte?\.?|expediente)\s*(?:n[°ºo]\.?\s*)?(\d{1,6}[-/]\d{1,8}(?:[-/]\d{2,4})?)", re.I)
RE_CUIT = re.compile(r"\b(30|33|34)-?(\d{8})-?(\d)\b")          # solo personas jurídicas
RE_TAGS = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def cuit_valido(c: str) -> bool:
    d = re.sub(r"\D", "", c or "")
    if len(d) != 11:
        return False
    s = sum(int(a) * b for a, b in zip(d[:10], [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]))
    v = 11 - s % 11
    v = 0 if v == 11 else v
    return v != 10 and v == int(d[10])


def extraer_expedientes(texto: str) -> list:
    vistos = []
    for m in RE_EXP_GDE.finditer(texto or ""):
        e = re.sub(r"\s+", "", m.group(0).upper())
        if e not in vistos:
            vistos.append(e)
    for m in RE_EXP_LOCAL.finditer(texto or ""):
        e = "EXP " + m.group(1)
        if e not in vistos:
            vistos.append(e)
    return vistos[:15]


def extraer_cuits_entidades(texto: str) -> list:
    out = []
    for m in RE_CUIT.finditer(texto or ""):
        c = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if cuit_valido(c) and c not in out:
            out.append(c)
    return out[:10]


def texto_html(data: bytes) -> str:
    t = data.decode("utf-8", "ignore")
    return re.sub(r"\s+", " ", html.unescape(RE_TAGS.sub(" ", t))).strip()


def texto_pdf(data: bytes):
    """Devuelve el texto o None si no hay librería para leer PDF."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        lector = PdfReader(io.BytesIO(data))
        partes = []
        for i, pag in enumerate(lector.pages):
            if i >= MAX_PAGINAS_PDF:
                break
            partes.append(pag.extract_text() or "")
        return re.sub(r"\s+", " ", " ".join(partes)).strip()
    except Exception:
        return ""


def analizar_contenido(cap: Captura):
    """Indicadores OBJETIVOS del documento (no se publica el texto; solo ayuda a la persona que revisa)."""
    es_pdf = cap.contenido[:5] == b"%PDF-"
    texto = texto_pdf(cap.contenido) if es_pdf else texto_html(cap.contenido)
    if texto is None:
        return ({"es_pdf": True, "caracteres": 0, "expedientes": [], "cuits_entidades": [], "contiene_posibles_dni": False},
                True, "pdf_no_procesado_falta_pypdf")
    ind = {"es_pdf": es_pdf, "caracteres": len(texto), "expedientes": extraer_expedientes(texto),
           "cuits_entidades": extraer_cuits_entidades(texto),
           "contiene_posibles_dni": bool(RE_DNI.search(texto) or RE_CUIL.search(texto))}
    requiere = len(texto) < 200
    motivo = ("pdf_sin_capa_de_texto" if es_pdf else "pagina_sin_texto_legible") if requiere else None
    return ind, requiere, motivo


# ---------------------------------------------------------------- Descubrimiento por sitemap
def parsear_sitemap(data: bytes):
    """Devuelve (es_indice, [(loc, lastmod)]). Rechaza XML con DOCTYPE/ENTITY."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_BYTES)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("sitemap rechazado: contiene DOCTYPE/ENTITY")
    root = ET.fromstring(data)
    es_indice = root.tag.endswith("sitemapindex")
    salida = []
    for nodo in root:
        loc = lastmod = None
        for h in nodo:
            if h.tag.endswith("loc"):
                loc = (h.text or "").strip()
            elif h.tag.endswith("lastmod"):
                lastmod = (h.text or "").strip()[:10]
        if loc:
            salida.append((loc, lastmod))
    return es_indice, salida


def descubrir_sitemap(f: dict, presupuesto: list) -> list:
    """URLs nuevas o modificadas de la fuente, mismo dominio, que cumplen el patrón. presupuesto=[capturas restantes]."""
    base = urlparse(f["url"])
    sm_url = f.get("sitemap_url") or f"{base.scheme}://{base.netloc}/sitemap.xml"
    desde = (f.get("ultima_revision") or "")[:10]
    try:
        patron = re.compile(f["patron_url"], re.I) if f.get("patron_url") else None
    except re.error:
        return []

    def bajar(u):
        if presupuesto[0] <= 0:
            return None
        presupuesto[0] -= 1
        c = capturar(u)
        time.sleep(PAUSA_SEG)
        return c if c.utilizable else None

    c = bajar(sm_url)
    if not c:
        return []
    try:
        es_indice, items = parsear_sitemap(c.contenido)
        if es_indice:
            hijos = sorted(items, key=lambda x: x[1] or "", reverse=True)[:5]
            items = []
            for loc, _ in hijos:
                ch = bajar(loc)
                if ch:
                    items += parsear_sitemap(ch.contenido)[1]
    except Exception:
        return []
    elegidas = []
    for loc, lastmod in sorted(items, key=lambda x: x[1] or "", reverse=True):
        if urlparse(loc).netloc.lower() != base.netloc.lower():
            continue
        if patron and not patron.search(loc):
            continue
        if desde and lastmod and lastmod < desde:
            continue
        if loc != f["url"] and loc not in elegidas:
            elegidas.append(loc)
        if len(elegidas) >= MAX_DESCUBIERTAS_POR_FUENTE:
            break
    return elegidas


def nombre_desde_url(u: str) -> str:
    seg = [s for s in urlparse(u).path.split("/") if s]
    return (seg[-1] if seg else urlparse(u).netloc)[:120]


# ---------------------------------------------------------------- Cola de revisión y registro
def mapa_slugs(tabla: str) -> dict:
    res = db().table(tabla).select("id,slug").execute()
    return {f["slug"]: f["id"] for f in (res.data or [])}


def proponer(agente, tipo, titulo, cap: Captura, club_id=None, inst_id=None, propuesta=None, texto_para_filtro=""):
    """Pasa el ítem por la mesa de agentes y lo inserta en cola_revision (privada) con sus votos.
    Devuelve 'nuevo' | 'duplicado' | 'bloqueado_legal'."""
    from mesa import evaluar, decidir   # import tardío: mesa importa este módulo
    previo = db().table("cola_revision").select("id,revisada_por,nota_revision") \
        .eq("url_fuente", cap.url).eq("hash_sha256", cap.sha256).execute()
    # lo que retiró la limpieza automática (por un filtro equivocado) puede volver a proponerse: se REABRE
    # el mismo ítem (la base no admite dos con la misma URL y huella).
    reabrible = lambda r: r.get("revisada_por") == "limpieza automática" and (r.get("nota_revision") or "").startswith("Falso positivo")
    if any(not reabrible(r) for r in previo.data or []):
        return "duplicado"
    reabrir = (previo.data or [None])[0]
    item = {"tipo": tipo, "titulo": titulo, "url_fuente": cap.url, "hash_sha256": cap.sha256,
            "http_status": cap.http, "propuesta": propuesta or {}, "texto": texto_para_filtro}
    votos = evaluar(item)
    estado, obs = decidir(votos)
    fila = {"agente": agente, "tipo": tipo, "club_id": club_id, "institucion_id": inst_id, "titulo": titulo[:300],
            "url_fuente": cap.url, "hash_sha256": cap.sha256, "http_status": cap.http,
            "propuesta": {**(propuesta or {}), "_mesa": {"observaciones": obs}},
            "veto_juridico": "; ".join(obs) if estado == "bloqueada_legal" else None, "estado": estado}
    if reabrir:
        res = db().table("cola_revision").update({**fila, "revisada_por": None, "revisada_en": None, "motivo_codigo": None,
                                                  "nota_revision": None}).eq("id", reabrir["id"]).execute()
    else:
        res = db().table("cola_revision").insert(fila).execute()
    if res.data:
        cola_id = res.data[0]["id"]
        db().table("agente_votos").upsert([{"cola_id": cola_id, "agente": v["agente"], "voto": v["voto"],
                                            "motivo": v["motivo"] or None} for v in votos], on_conflict="cola_id,agente").execute()
    return "bloqueado_legal" if estado == "bloqueada_legal" else "nuevo"


# ---------------------------------------------------------------- Fuentes
SLUG_BROWN = "instituto-municipal-del-deporte-almirante-brown"
# Solo se usan si todavía no corriste db/09 (tabla fuentes_monitoreadas inexistente).
FUENTES_RESPALDO = [
    {"club": SLUG_BROWN, "nombre": "Boletín Oficial Alte. Brown - Enero 2026 (decretos)", "portal_origen": "boletin_municipal",
     "url": "https://files.brown.gob.ar/brown-web/bundles/site/pdf/boletin_oficial/PQ-Enero-Decretos-2026.pdf"},
    {"club": SLUG_BROWN, "nombre": "Ficha del club en el padrón web de FABA", "portal_origen": "sitio_oficial",
     "url": "https://basquetadaptado.com.ar/clubes/instituto-municipal-del-deporte-almirante-brown/"},
    {"inst": "faba", "nombre": "Autoridades FABA (web oficial)", "portal_origen": "sitio_oficial",
     "url": "https://basquetadaptado.com.ar/autoridades/"},
    {"inst": "copar", "nombre": "Autoridades COPAR (web oficial)", "portal_origen": "sitio_oficial",
     "url": "https://www.coparg.org.ar/nosotros/"},
]


def _fecha(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def vencida(f: dict, momento=None) -> bool:
    ult = _fecha(f.get("ultima_revision")) if f.get("ultima_revision") else None
    if ult is None:
        return True
    return (momento or ahora()) - ult >= timedelta(days=int(f.get("frecuencia_dias") or 7)) - timedelta(hours=2)


def cargar_fuentes(momento=None):
    """Fuentes activas o caídas (se reintentan) cuya revisión venció. None = la tabla no existe todavía."""
    from supa import SupaError
    try:
        filas = db().table("fuentes_monitoreadas").select("*").in_("estado", ["activa", "caida"]).execute().data or []
    except SupaError as e:
        if e.status in (404,) or e.codigo in ("42P01", "PGRST205"):
            return None
        raise
    forzar = os.environ.get("FORZAR_REVISION") == "1"          # corrida manual: revisar todo aunque no haya vencido
    filas = [f for f in filas if f.get("tipo") != "red_oficial" and (forzar or vencida(f, momento))]   # redes: ingesta_redes.py
    return sorted(filas, key=lambda f: f.get("ultima_revision") or "")[:MAX_FUENTES_POR_CICLO]


def fuentes_de_respaldo():
    clubes, insts = mapa_slugs("clubes"), mapa_slugs("instituciones")
    out = []
    for o in FUENTES_RESPALDO:
        out.append({**o, "id": None, "club_id": clubes.get(o.get("club")), "institucion_id": insts.get(o.get("inst"))})
    return out


def registrar_estado_fuente(f: dict, utilizable: bool, bloqueada: bool, http: int):
    if not f.get("id"):
        return
    fallos = int(f.get("fallos_consecutivos") or 0)
    if utilizable:
        estado, fallos = "activa", 0
    elif bloqueada:
        estado = "bloqueada_robots"      # se respeta: una persona decide si se reactiva
    else:
        fallos += 1
        estado = "caida" if fallos >= 3 else f.get("estado", "activa")
    db().table("fuentes_monitoreadas").update({
        "estado": estado, "fallos_consecutivos": fallos, "ultimo_status": http,
        "ultima_revision": ahora().isoformat()}).eq("id", f["id"]).execute()


def actualizar_fuente(f: dict, cap: Captura):
    registrar_estado_fuente(f, cap.utilizable, cap.bloqueada, cap.http)


def urls_vistas(fuente_id) -> dict:
    if not fuente_id:
        return {}
    res = db().table("fuente_urls_vistas").select("url,hash_sha256").eq("fuente_id", fuente_id).execute()
    return {r["url"]: r["hash_sha256"] for r in (res.data or [])}


def registrar_vista(fuente_id, url, sha, requiere):
    if not fuente_id:
        return
    db().table("fuente_urls_vistas").upsert({"fuente_id": fuente_id, "url": url, "hash_sha256": sha,
                                            "requiere_revision_humana": requiere, "ultima_vez": ahora().isoformat()},
                                           on_conflict="fuente_id,url").execute()


RE_VOLATIL = re.compile(r"\b\d{1,2}[:.]\d{2}(?::\d{2})?\b|\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b|\b\d{1,2} de [a-z]+(?: de \d{4})?\b|"
                        r"\b(?:hace|visitas?|vistas?|me gusta|seguidores)\b[^.]{0,30}|\b\d+\b")


def hash_estable(cap: Captura) -> str:
    """Huella del CONTENIDO: en HTML ignora fechas, horas, contadores y números sueltos, que cambian a diario
    sin que cambie el documento. En PDF y otros archivos se usa el hash del archivo."""
    if cap.contenido[:5] == b"%PDF-" or not cap.contenido:
        return cap.sha256
    t = _norm(texto_html(cap.contenido))
    return hashlib.sha256(RE_VOLATIL.sub(" ", t).encode()).hexdigest()


def procesar_url(f: dict, url: str, cap: Captura, titulo: str, vistas: dict) -> str:
    anterior = vistas.get(url)
    estable = hash_estable(cap)
    if anterior in (cap.sha256, estable):
        return "sin_cambios"
    ind, requiere, motivo = analizar_contenido(cap)
    prop = {"portal_origen": f.get("portal_origen") or "sitio_oficial", "fuente_id": f.get("id"),
            "indicadores": ind, "requiere_ocr_o_revision_humana": requiere, "motivo_revision": motivo,
            "hash_anterior": anterior}
    tipo = "documento_cambio" if anterior else "documento_nuevo"
    r = proponer("rastreador", tipo, titulo, cap, f.get("club_id"), f.get("institucion_id"), prop)
    registrar_vista(f.get("id"), url, estable, requiere)
    vistas[url] = estable
    return r


# ---------------------------------------------------------------- Búsqueda dirigida en índices
TIPOS_INDICE = {"boletin_oficial", "compras", "portal_transparencia", "concejo_deliberante"}
MAX_NUEVOS_POR_INDICE = 6         # por corrida: el resto se cubre en las corridas diarias siguientes
RE_ENLACE = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
RE_DOC_URL = re.compile(r"(?i)\.(pdf|docx?|xlsx?|odt|ods)(\?|$)|bolet[ií]n|decreto|ordenanza|resoluci|licitaci|norma|presupuest|"
                        r"edici[oó]n|dataset|contrataci|pliego|expediente|digesto|legislaci")
RE_NO_DOC = re.compile(r"(?i)facebook|twitter|x\.com|instagram|youtube|whatsapp|wa\.me|t\.me|linkedin|mailto:|login|"
                       r"usuarios/|sharer|/tag/|/author/|/feed")
RE_TEMA_FUERTE = re.compile(r"\b(basquet(bol)? adaptado|basquet(bol)? (en|sobre) sillas?|sillas? de ruedas|paralimpic\w*|"
                            r"deporte adaptado|deporte inclusivo)\b")
RE_TEMA_ADAPTADO = re.compile(RE_TEMA_FUERTE.pattern[:-3] + r"|discapacidad)\b")
RE_TEMA_DEPORTE = re.compile(r"\b(deportes?|deportiv\w*|polideportivo|basquet\w*|atletas?|seleccion)\b")
RE_INSTITUCIONES = re.compile(r"\b(faba|copar|enard|federacion argentina de basquet\w* adaptado|comite paralimpico)\b")
RE_FONDOS = re.compile(r"\b(subsidios?|becas?|viaticos?|aportes?|transferencias?|convenios?|adjudica\w*)\b")


def enlaces_documento(data: bytes, base: str) -> list:
    """Enlaces del índice que parecen documentos (PDF, normas, licitaciones, ediciones), en el orden de la página."""
    dominio = urlparse(base).netloc.split(":")[0].removeprefix("www.")
    out = []
    for h, txt in RE_ENLACE.findall(data.decode("utf-8", "ignore")):
        u = urljoin(base, html.unescape(h.strip()))
        if not u.startswith("http") or RE_NO_DOC.search(u) or u.rstrip("/") == base.rstrip("/"):
            continue
        host = urlparse(u).netloc.split(":")[0].removeprefix("www.")
        mismo = host == dominio or host.endswith("." + dominio) or dominio.endswith("." + host)
        oficial = host.endswith((".gob.ar", ".gov.ar", ".edu.ar"))
        if (mismo or oficial) and (RE_DOC_URL.search(u) or RE_DOC_URL.search(txt)) and u not in out:
            out.append(u)
    return out


RE_FUERA_DE_CONTENIDO = re.compile(r"<(script|style|noscript|svg|nav|header|footer|aside|form|menu)\b[^>]*>.*?</\1>", re.S | re.I)
RE_MENU = re.compile(r"""<(ul|div)\b[^>]*(?:class|id)=["'][^"']*(?:menu|nav|sidebar|footer|header|breadcrumb|widget)[^"']*["'][^>]*>.*?</\1>""",
                     re.S | re.I)
CERCANIA = 250          # "deporte" y "discapacidad/adaptado" tienen que estar a menos de esto (caracteres)


def texto_contenido(data: bytes) -> str:
    """Texto del CONTENIDO de una página: sin menús, encabezado, pie ni barras laterales (que repiten
    "Deportes" o "Discapacidad" en todas las páginas de un sitio municipal)."""
    t = data.decode("utf-8", "ignore")
    m = re.search(r"<(main|article)\b[^>]*>(.*)</\1>", t, re.S | re.I)
    t = m.group(2) if m else t
    t = RE_MENU.sub(" ", RE_FUERA_DE_CONTENIDO.sub(" ", t))
    return re.sub(r"\s+", " ", html.unescape(RE_TAGS.sub(" ", t))).strip()


def _cerca(t: str, rx_a, rx_b, dist=CERCANIA) -> bool:
    pos_b = [m.start() for m in rx_b.finditer(t)]
    return any(abs(a.start() - b) <= dist for a in rx_a.finditer(t) for b in pos_b)


def relevancia(texto: str, alias: dict) -> list:
    """Por qué un documento interesa (marcas objetivas). Lista vacía = no se propone."""
    t = _norm(texto).replace(".", "")
    marcas = []
    if RE_INSTITUCIONES.search(t):
        marcas.append("menciona_faba_copar_enard")
    if _cerca(t, RE_TEMA_FUERTE, RE_TEMA_DEPORTE):
        marcas.append("deporte_y_discapacidad")
    elif _cerca(t, RE_TEMA_ADAPTADO, RE_TEMA_DEPORTE) and (RE_FONDOS.search(t) or any(a in t for a in alias)):
        # "discapacidad" a secas (p. ej. exenciones de una ordenanza fiscal) solo cuenta con fondos o un club nombrado
        marcas.append("deporte_y_discapacidad")
    for a, slug in alias.items():
        if re.search(r"(?<![a-z0-9@])" + re.escape(a) + r"(?![a-z0-9])", t):
            marcas.append("menciona_club:" + slug)
    if marcas and RE_FONDOS.search(t):
        marcas.append("menciona_fondos")
    return sorted(set(marcas))


def procesar_indice(f: dict, cap: Captura, vistas: dict, presupuesto: list, alias: dict, club_por_slug: dict) -> list:
    """El índice no se propone: se recorren sus documentos nuevos y solo se proponen los relevantes."""
    resultados = []
    registrar_vista(f.get("id"), f["url"], hash_estable(cap), False)
    nuevos = [u for u in enlaces_documento(cap.contenido, f["url"]) if u not in vistas]
    leidos = 0
    for u in nuevos:
        if leidos >= MAX_NUEVOS_POR_INDICE:
            break
        if presupuesto[0] <= 0:
            break
        presupuesto[0] -= 1
        c2 = capturar(u)
        time.sleep(PAUSA_SEG)
        if c2.bloqueada:
            resultados.append("bloqueado"); continue
        if not c2.utilizable:
            continue
        leidos += 1
        es_pdf = c2.contenido[:5] == b"%PDF-"
        estable = hash_estable(c2)
        if not es_pdf:
            hijos = [h for h in enlaces_documento(c2.contenido, u) if h not in vistas and h not in nuevos]
            if len(hijos) >= 5:                    # sub-índice (p. ej. "Boletín 2021"): se recorre, no se propone
                nuevos.extend(hijos)
                registrar_vista(f.get("id"), u, estable, False)
                vistas[u] = estable
                resultados.append("subindice"); continue
        texto = (texto_pdf(c2.contenido) if es_pdf else texto_contenido(c2.contenido)) or ""
        marcas = relevancia(texto, alias)
        if not marcas:
            registrar_vista(f.get("id"), u, estable, len(texto) < 200)       # leído y descartado: no se vuelve a bajar
            vistas[u] = estable
            resultados.append("no_relevante"); continue
        club = next((club_por_slug[m.split(":", 1)[1]] for m in marcas if m.startswith("menciona_club:")), None)
        ind, requiere, motivo = analizar_contenido(c2)
        prop = {"portal_origen": f.get("portal_origen") or "sitio_oficial", "fuente_id": f.get("id"), "indice": f["url"],
                "indicadores": ind, "coincidencias": marcas, "requiere_ocr_o_revision_humana": requiere, "motivo_revision": motivo}
        r = proponer("rastreador", "documento_nuevo", f"{f['nombre']}: {nombre_desde_url(u)}", c2,
                     club["id"] if club else f.get("club_id"), None if club else f.get("institucion_id"), prop)
        registrar_vista(f.get("id"), u, estable, requiere)
        vistas[u] = estable
        resultados.append(r)
    return resultados


def contexto_jurisdicciones():
    """alias de clubes por institución-jurisdicción (según bot/catalogo_fuentes.json) y clubes por slug."""
    try:
        from cargar_fuentes import catalogo
        from actualidad_redes import alias_de_clubes
        cat = catalogo()
    except Exception:
        return {}, {}, {}
    clubes = db().table("clubes").select("id,slug,nombre,instagram").execute().data or []
    por_slug = {c["slug"]: c for c in clubes}
    inst = {i["id"]: i["slug"] for i in db().table("instituciones").select("id,slug").execute().data or []}
    por_juris = {}
    for club_slug, juris in cat.get("clubes", {}).items():
        for j in juris:
            if club_slug in por_slug:
                por_juris.setdefault(j, []).append(por_slug[club_slug])
    alias = {j: {a: next(c["slug"] for c in cs if c["id"] == cid) for a, cid in alias_de_clubes(cs).items() if len(a) >= 4}
             for j, cs in por_juris.items()}
    return alias, inst, por_slug


def ciclo():
    fuentes = cargar_fuentes()
    modo = "tabla"
    if fuentes is None:
        modo, fuentes = "respaldo", fuentes_de_respaldo()
    ej = db().table("agente_ejecuciones").insert({"agente": "rastreador", "objetivos": len(fuentes)}).execute()
    ej_id = ej.data[0]["id"] if ej.data else None
    presupuesto = [MAX_CAPTURAS_POR_CICLO]
    alias_juris, inst_slug, club_por_slug = contexto_jurisdicciones()
    ok = bloq = err = 0
    detalle = []
    for f in fuentes:
        try:
            r = _procesar_fuente(f, presupuesto, alias_juris, inst_slug, club_por_slug, detalle)
        except Exception as e:                      # una fuente con problemas no frena a las demás
            r = "err"
            print(f"  {f.get('nombre', '')[:60]}: error inesperado ({type(e).__name__}: {str(e)[:120]})", flush=True)
            detalle.append({"url": f.get("url"), "resultado": f"error:{type(e).__name__}"})
        ok += r == "ok"; bloq += r == "bloq"; err += r == "err"
    if ej_id:
        db().table("agente_ejecuciones").update({"fin": ahora().isoformat(), "ok": ok, "bloqueados": bloq, "errores": err,
                                                 "detalle": {"modo": modo, "fuentes": detalle}}).eq("id", ej_id).execute()
    print(f"modo={modo} fuentes={len(fuentes)} ok={ok} bloqueados={bloq} errores={err} "
          f"(todo queda en cola_revision para revisión humana)")


def _procesar_fuente(f, presupuesto, alias_juris, inst_slug, club_por_slug, detalle) -> str:
    """Procesa una fuente. Devuelve ok | bloq | err | tope."""
    if (f.get("club_id") is None) == (f.get("institucion_id") is None):
        detalle.append({"url": f["url"], "resultado": "destino_inexistente"}); return "err"
    if presupuesto[0] <= 0:
        detalle.append({"url": f["url"], "resultado": "pospuesta_por_tope"}); return "tope"
    presupuesto[0] -= 1
    cap = capturar(f["url"])
    time.sleep(PAUSA_SEG)
    actualizar_fuente(f, cap)
    if cap.bloqueada:
        detalle.append({"url": f["url"], "resultado": f"bloqueado_{cap.http or cap.motivo}"}); return "bloq"
    if not cap.utilizable:
        print(f"  {f['nombre'][:60]}: no se pudo leer ({cap.motivo or cap.http})", flush=True)
        detalle.append({"url": f["url"], "resultado": cap.motivo or f"http_{cap.http}"}); return "err"
    vistas = urls_vistas(f.get("id"))
    resultados = []
    es_indice = cap.contenido[:5] != b"%PDF-" and b"<a" in cap.contenido.lower()   # una página con enlaces, no un archivo
    if f.get("tipo") in TIPOS_INDICE and not f.get("usa_sitemap") and es_indice:
        juris = inst_slug.get(f.get("institucion_id"), "")
        resultados = procesar_indice(f, cap, vistas, presupuesto, alias_juris.get(juris, {}), club_por_slug)
    elif not f.get("usa_sitemap"):          # con sitemap, la portada es solo el punto de partida
        resultados.append(procesar_url(f, f["url"], cap, f["nombre"], vistas))
    else:
        for u in descubrir_sitemap(f, presupuesto):
            if presupuesto[0] <= 0:
                break
            presupuesto[0] -= 1
            c2 = capturar(u)
            time.sleep(PAUSA_SEG)
            if c2.utilizable:
                resultados.append(procesar_url(f, u, c2, f"{f['nombre']}: {nombre_desde_url(u)}", vistas))
            elif c2.bloqueada:
                resultados.append("bloqueado")
    print(f"  {f['nombre'][:60]}: propuestos={resultados.count('nuevo')} no_relevantes={resultados.count('no_relevante')} "
          f"sin_cambios={resultados.count('sin_cambios')} presupuesto_restante={presupuesto[0]}", flush=True)
    detalle.append({"url": f["url"], "resultado": "ok", "nuevos": resultados.count("nuevo"),
                    "leidos_no_relevantes": resultados.count("no_relevante"),
                    "sin_cambios": resultados.count("sin_cambios"), "bloqueados_mesa": resultados.count("bloqueado_legal")})
    return "ok"


if __name__ == "__main__":
    ciclo()
