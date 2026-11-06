"""Analista de PDF: lee CADA página (con OCR si es un escaneo), busca los temas que le importan al observatorio
y arma una captura de la página con el pasaje resaltado, para citar la fuente con imagen.

Nada de esto se publica solo: los hallazgos van a la cola de revisión y una persona decide qué captura
se publica. La captura lleva al pie la fuente, la página, la huella del archivo y la fecha.

Temas (marcas objetivas, sin calificativos):
  deporte_adaptado      básquet adaptado / en silla de ruedas, deporte adaptado, paralímpico…
  discapacidad_deporte  "discapacidad" cerca de deporte o de fondos (subsidio, beca, viático…)
  instituto_deporte     Instituto Municipal del Deporte
  juegos_bonaerenses    Juegos Bonaerenses
  viajes_deportivos     viaje / traslado / alojamiento / micro cerca de deporte, torneo o delegación
  federaciones          FABA, COPAR, ENARD, Comité Paralímpico
"""
import io
import re
import time
import unicodedata
from datetime import datetime, timezone

MAX_PAGINAS = 80
MAX_PAGINAS_OCR = 30
MAX_CAPTURAS = 4
TIEMPO_MAX_SEG = 150
VENTANA = 250

RX = lambda p: re.compile(p.replace(" ", r"\s+"))     # el texto de un PDF puede traer saltos de línea entre palabras
T_FUERTE = RX(r"\b(basquet(bol)? adaptado|basquet(bol)? (en|sobre) sillas?|sillas? de ruedas|paralimpic\w*|"
              r"deporte adaptado|deportes adaptados|deporte inclusivo|actividad fisica adaptada)\b")
T_DISCAP = RX(r"\b(discapacidad\w*|personas? con discapacidad)\b")
T_DEPORTE = RX(r"\b(deportes?|deportiv\w*|deportistas?|polideportivo|basquet\w*|atletas?|torneos?|competencias?|"
               r"delegacion(es)?|juegos bonaerenses)\b")
T_FONDOS = RX(r"\b(subsidios?|becas?|viaticos?|aportes?|transferencias?|convenios?|adjudica\w*|contrataci\w*|"
              r"licitaci\w*|orden(es)? de compra|pagos?|partidas?)\b")
T_INSTITUTO = RX(r"\binstituto municipal (de |del )?(los )?deportes?\b")
T_JUEGOS = RX(r"\bjuegos bonaerenses\b")
T_VIAJE = RX(r"\b(viajes?|traslados?|transporte|micros?|omnibus|colectivos?|alojamiento|hoteleria|hotel(es)?|"
             r"pasajes?|viaticos?|combis?)\b")
T_FEDER = RX(r"\b(faba|copar|enard|comite paralimpico|federacion argentina de basquet\w* (en silla|adaptado))\b")
RE_TRIBUTARIA = RX(r"\bordenanza (fiscal|impositiva|tarifaria)\b|\bcodigo (fiscal|tributario)\b")
# montos: $ 1.234.567,89 | $1234567 | U$S 240.000 | 240.000 dolares
RE_MONTO = re.compile(r"(?i)(?:u\$s|us\$|usd|\$)\s?\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|(?:u\$s|us\$|usd|\$)\s?\d{4,}(?:,\d{1,2})?|"
                      r"\b\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?\s?(?:pesos|dolares|dólares)")

NOMBRE_TEMA = {"deporte_adaptado": "Deporte adaptado", "discapacidad_deporte": "Discapacidad y deporte",
               "instituto_deporte": "Instituto Municipal del Deporte", "juegos_bonaerenses": "Juegos Bonaerenses",
               "viajes_deportivos": "Viajes deportivos", "federaciones": "FABA / COPAR / ENARD"}


def _n1(c: str) -> str:
    """Normaliza un carácter sin cambiar la longitud: así las posiciones del texto normalizado sirven para el original."""
    d = unicodedata.normalize("NFD", c)
    return (d[0] if d else c).lower()


def normalizar(t: str) -> str:
    return "".join(" " if c in "\r\n\t\f\v\xa0" else _n1(c) for c in t)


def _cerca(t, ra, rb, dist=VENTANA):
    pb = [m.start() for m in rb.finditer(t)]
    return [m for m in ra.finditer(t) if any(abs(m.start() - b) <= dist for b in pb)]


def coincidencias(t: str) -> list:
    """(tema, inicio, fin) sobre el texto normalizado de una página."""
    out = [("deporte_adaptado", m.start(), m.end()) for m in T_FUERTE.finditer(t)]
    out += [("instituto_deporte", m.start(), m.end()) for m in T_INSTITUTO.finditer(t)]
    out += [("juegos_bonaerenses", m.start(), m.end()) for m in T_JUEGOS.finditer(t)]
    out += [("federaciones", m.start(), m.end()) for m in T_FEDER.finditer(t)]
    if not RE_TRIBUTARIA.search(t[:3000]):     # las normas tributarias nombran exenciones a entidades deportivas y a personas con discapacidad
        dd = _cerca(t, T_DISCAP, T_DEPORTE)
        out += [("discapacidad_deporte", m.start(), m.end()) for m in dd if _cerca(t[max(0, m.start() - VENTANA):m.end() + VENTANA], T_DISCAP, T_FONDOS)
                or T_FUERTE.search(t)]
    out += [("viajes_deportivos", m.start(), m.end()) for m in _cerca(t, T_VIAJE, T_DEPORTE, 160)]
    return out


def montos_cerca(texto: str, ini: int, fin: int, ventana=400) -> list:
    tramo = texto[max(0, ini - ventana):fin + ventana]
    vistos = []
    for m in RE_MONTO.finditer(tramo):
        v = re.sub(r"\s+", " ", m.group(0)).strip()
        if v not in vistos:
            vistos.append(v)
    return vistos[:6]


def extracto(texto: str, ini: int, fin: int, ventana=220) -> str:
    a, b = max(0, ini - ventana), min(len(texto), fin + ventana)
    return ("…" if a else "") + re.sub(r"\s+", " ", texto[a:b]).strip() + ("…" if b < len(texto) else "")


# ---------------------------------------------------------------- lectura de páginas
class Pagina:
    """Texto de una página y, para cada carácter, su caja en píxeles de la imagen renderizada (escala ESCALA)."""
    def __init__(self, n, texto, cajas, ocr):
        self.n, self.texto, self.cajas, self.ocr = n, texto, cajas, ocr


ESCALA = 2.0      # 144 ppp: suficiente para OCR y para una captura legible


def _texto_pdfium(page, alto_pt):
    tp = page.get_textpage()
    n = tp.count_chars()
    chars, cajas = [], []
    for i in range(n):
        c = tp.get_text_range(i, 1)
        chars.append(c or " ")
        try:
            l, b, r, t = tp.get_charbox(i)
            cajas.append((l * ESCALA, (alto_pt - t) * ESCALA, r * ESCALA, (alto_pt - b) * ESCALA))
        except Exception:
            cajas.append(None)
    tp.close()
    return "".join(chars), cajas


def _limpiar_para_ocr(imagen):
    """Escala de grises y umbral: el texto resaltado con color (o con fondo gris) se pierde si no se limpia."""
    return imagen.convert("L").point(lambda v: 255 if v > 140 else 0)


def _texto_ocr(imagen):
    import pytesseract
    d = pytesseract.image_to_data(_limpiar_para_ocr(imagen), lang="spa", config="--psm 3", output_type=pytesseract.Output.DICT)
    chars, cajas, linea_previa = [], [], None
    for i, w in enumerate(d["text"]):
        w = (w or "").strip()
        if not w:
            continue
        linea = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        if chars:
            chars.append("\n" if linea != linea_previa else " "); cajas.append(None)
        linea_previa = linea
        x, y, ww, hh = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        for k, c in enumerate(w):         # caja aproximada por letra, repartiendo el ancho de la palabra
            cajas.append((x + ww * k / len(w), y, x + ww * (k + 1) / len(w), y + hh))
            chars.append(c)
    return "".join(chars), cajas


def paginas(data: bytes, ocr=True, max_ocr=MAX_PAGINAS_OCR, tiempo_max=TIEMPO_MAX_SEG):
    """Genera (Pagina, imagen PIL) para cada página. La imagen se renderiza solo si hace falta (OCR o captura)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    try:
        usadas_ocr, t0 = 0, time.time()
        for i in range(min(len(pdf), MAX_PAGINAS)):
            if time.time() - t0 > tiempo_max:
                break
            page = pdf[i]
            alto = page.get_height()
            texto, cajas = _texto_pdfium(page, alto)
            usa_ocr = False
            if len(re.sub(r"\s", "", texto)) < 40 and ocr and usadas_ocr < max_ocr:
                img = page.render(scale=ESCALA).to_pil().convert("RGB")
                try:
                    texto, cajas = _texto_ocr(img); usa_ocr = True; usadas_ocr += 1
                except Exception:
                    pass
            yield Pagina(i + 1, texto, cajas, usa_ocr), page
    finally:
        pdf.close()


def _unir_cajas(cajas):
    """Une las cajas de letras contiguas de una misma línea en un solo rectángulo (el resaltado se lee mejor)."""
    out = []
    for c in cajas:
        if out:
            l, t, r, b = out[-1]
            alto = max(b - t, 1)
            if abs(c[1] - t) < alto * 0.6 and -alto < c[0] - r < alto * 1.5:
                out[-1] = (min(l, c[0]), min(t, c[1]), max(r, c[2]), max(b, c[3]))
                continue
        out.append(tuple(c))
    return out


def _fuente(tam):
    from PIL import ImageFont
    for ruta in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(ruta, tam)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:
        return ImageFont.load_default()


def _captura(page, cajas_resaltar, pie: str):
    from PIL import Image, ImageDraw, ImageFont
    img = page.render(scale=ESCALA).to_pil().convert("RGB")
    W, H = img.size
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dib = ImageDraw.Draw(capa)
    ys = []
    for (l, t, r, b) in _unir_cajas(cajas_resaltar):
        dib.rectangle([l - 2, t - 2, r + 2, b + 2], fill=(255, 221, 0, 110), outline=(220, 38, 38, 255), width=2)
        ys += [t, b]
    img = Image.alpha_composite(img.convert("RGBA"), capa).convert("RGB")
    # recorte: toda la línea de ancho y una franja alrededor del pasaje (contexto suficiente para leerlo)
    if ys:
        y0, y1 = max(0, min(ys) - 420), min(H, max(ys) + 420)
        if y1 - y0 < 700:
            extra = (700 - (y1 - y0)) // 2
            y0, y1 = max(0, y0 - extra), min(H, y1 + extra)
        img = img.crop((0, int(y0), W, int(y1)))
    fuente = _fuente(17)
    import textwrap
    lineas = textwrap.wrap(pie, max(60, img.width // 10))[:4]
    alto_pie = 14 + 24 * len(lineas)
    lienzo = Image.new("RGB", (img.width, img.height + alto_pie), (15, 23, 42))
    lienzo.paste(img, (0, 0))
    d2 = ImageDraw.Draw(lienzo)
    for k, ln in enumerate(lineas):
        d2.text((12, img.height + 8 + 24 * k), ln, fill=(255, 255, 255), font=fuente)
    if lienzo.width > 1400:
        lienzo = lienzo.resize((1400, int(lienzo.height * 1400 / lienzo.width)))
    buf = io.BytesIO()
    lienzo.save(buf, "JPEG", quality=72, optimize=True)
    return buf.getvalue()


def analizar(data: bytes, url: str = "", sha256: str = "", ocr=True, capturas=True,
             max_ocr=MAX_PAGINAS_OCR, tiempo_max=TIEMPO_MAX_SEG) -> dict:
    """Devuelve {'paginas', 'paginas_ocr', 'texto', 'hallazgos': [...], 'capturas': [(bytes, meta)]}.
    Cada hallazgo: tema, pagina, extracto, montos. Las capturas son de las páginas con hallazgos (máx. MAX_CAPTURAS)."""
    hallazgos, caps, textos, n_pag, n_ocr = [], [], [], 0, 0
    hoy = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    for pag, page in paginas(data, ocr=ocr, max_ocr=max_ocr, tiempo_max=tiempo_max):
        n_pag += 1; n_ocr += pag.ocr
        textos.append(pag.texto)
        tn = normalizar(pag.texto)
        hs = coincidencias(tn)
        if not hs:
            continue
        por_tema = {}
        for tema, a, b in hs:
            por_tema.setdefault(tema, []).append((a, b))
        for tema, spans in por_tema.items():
            a, b = spans[0]
            hallazgos.append({"tema": tema, "pagina": pag.n, "ocr": pag.ocr, "veces": len(spans),
                              "extracto": extracto(pag.texto, a, b)[:600], "montos": montos_cerca(pag.texto, a, b)})
        if capturas and len(caps) < MAX_CAPTURAS:
            spans = [(a, b) for (_, a, b) in hs]
            for (a, b) in list(spans):           # también se resaltan los montos que están cerca del pasaje
                ini = max(0, a - 400)
                spans += [(ini + m.start(), ini + m.end()) for m in RE_MONTO.finditer(pag.texto[ini:b + 400])]
            cajas = [c for (a, b) in spans for c in pag.cajas[a:b] if c and c[2] - c[0] > 0.5]
            temas = sorted(por_tema)
            pie = (f"Fuente: {url or 'documento cargado'} · página {pag.n}{' (texto leído por OCR)' if pag.ocr else ''} · "
                   f"SHA-256 {sha256[:16]}… · captura AuditaDeporte {hoy} · temas: {', '.join(NOMBRE_TEMA[t] for t in temas)}")
            try:
                caps.append((_captura(page, cajas[:400], pie), {"pagina": pag.n, "temas": temas, "ocr": pag.ocr}))
            except Exception:
                pass
    return {"paginas": n_pag, "paginas_ocr": n_ocr, "texto": "\n".join(textos), "por_pagina": textos,
            "hallazgos": hallazgos, "capturas": caps}


def hallazgos_texto(texto: str) -> list:
    """Los mismos temas sobre una página web (sin captura: la captura es solo para PDF)."""
    t = normalizar(texto)
    out, vistos = [], set()
    for tema, a, b in coincidencias(t):
        if tema in vistos:
            continue
        vistos.add(tema)
        out.append({"tema": tema, "pagina": 1, "ocr": False, "veces": 1, "extracto": extracto(texto, a, b)[:600],
                    "montos": montos_cerca(texto, a, b)})
    return out


def disponible() -> bool:
    try:
        import pypdfium2  # noqa: F401
        return True
    except ImportError:
        return False


def temas_de(hallazgos: list) -> list:
    return sorted({h["tema"] for h in hallazgos})


def subir_capturas(cliente, sha256: str, caps: list) -> list:
    """Sube las capturas al depósito PRIVADO 'capturas'. Devuelve [{ruta, pagina, temas, ocr}] para la cola de revisión."""
    out = []
    for datos, meta in caps:
        ruta = f"{sha256}/pagina-{meta['pagina']}.jpg"
        try:
            cliente.subir_archivo("capturas", ruta, datos, "image/jpeg")
            out.append({"ruta": ruta, **meta})
        except Exception as e:                       # sin captura el documento igual se propone
            print(f"  captura no subida ({ruta}): {str(e)[:100]}", flush=True)
    return out


def es_relevante(hallazgos: list) -> bool:
    """Viajes a secas no alcanza (todo municipio paga micros): tiene que haber otro tema o un monto cerca."""
    temas = temas_de(hallazgos)
    if any(t != "viajes_deportivos" for t in temas):
        return True
    return any(h["montos"] for h in hallazgos if h["tema"] == "viajes_deportivos")


def resumen_hallazgos(hallazgos: list, maximo=12) -> list:
    """Lo que ve la persona que revisa: por tema y página, con el pasaje y los montos cercanos."""
    return [{k: h[k] for k in ("tema", "pagina", "ocr", "veces", "extracto", "montos")} for h in hallazgos[:maximo]]
