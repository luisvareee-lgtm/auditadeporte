"""Extrae datos estructurados de un boletín: números de normas publicadas y adjudicaciones.
Sirven para reglas objetivas (huecos de numeración, posible fraccionamiento de compras). No interpreta ni califica."""
import re

from analista_pdf import normalizar

MESES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MESES["setiembre"] = 9

# encabezado de norma: al principio de una línea y en mayúsculas ("DECRETO N° 820", "RESOLUCIÓN Nº 45/2026").
# Las menciones dentro del texto ("visto el Decreto N° 123/20") no cuentan: son normas citadas, no publicadas ahí.
RE_ENCABEZADO = re.compile(r"(?m)^[ \t]*(DECRETO|RESOLUCI[OÓ]N|ORDENANZA)\s*(?:N[ROÚMERO°º\"”*?.o:\s]{0,8})\s*(\d{1,5})(?:\s*/\s*(20\d\d|\d\d)\b)?")
RE_ANIO = re.compile(r"\bde\s+(20\d\d)\b|\b(20\d\d)\b")
RE_FECHA = re.compile(r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+(?:de|del)\s+(20\d\d)\b")
RE_ADJ = re.compile(r"adjudic\w*\s.{0,220}?(?:a la firma|a la empresa|al proveedor|a favor de(?: la firma| la empresa)?)\s+(.{3,90}?)(?=,|;|\s+cuit\b|\s+c\.u\.i\.t|\s+por\s|\s+\(|\s+en\s+la\s+suma|\s+la\s+suma|\n)",
                    re.S)
RE_PESOS = re.compile(r"\$\s?(\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d{4,}(?:,\d{1,2})?)")
RE_MODALIDAD = re.compile(r"compra directa|concurso de precios|licitacion privada|licitacion publica|contratacion directa")
RE_SOCIEDAD = re.compile(r"\b(s\.?\s?a\.?|s\.?\s?r\.?\s?l\.?|s\.?\s?a\.?\s?s\.?|s\.?\s?h\.?)\s*$")
TIPO = {"decreto": "decreto", "resolucion": "resolucion", "ordenanza": "ordenanza"}


def _monto(txt: str):
    t = txt.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        v = float(t)
        return v if v > 0 else None
    except ValueError:
        return None


def normas(texto: str, anio_doc: int = None) -> list:
    """[(tipo, numero, anio)] de los encabezados de normas que aparecen en el texto de una página."""
    out = []
    for m in RE_ENCABEZADO.finditer(texto):
        tipo = TIPO.get(normalizar(m.group(1)))
        num = int(m.group(2))
        anio = m.group(3)
        if anio:
            anio = int(anio) if len(anio) == 4 else 2000 + int(anio)
        else:
            ma = RE_ANIO.search(texto[m.end():m.end() + 300])
            anio = int(ma.group(1) or ma.group(2)) if ma else anio_doc
        if tipo and anio and 0 < num < 100000:
            out.append((tipo, num, anio))
    return out


def fecha_cerca(tn: str, pos: int):
    previas = [m for m in RE_FECHA.finditer(tn[max(0, pos - 2500):pos + 200])]
    if not previas:
        return None
    d, mes, a = previas[-1].groups()
    try:
        return f"{int(a):04d}-{MESES[mes]:02d}-{int(d):02d}"
    except (KeyError, ValueError):
        return None


def normalizar_proveedor(p: str) -> str:
    t = re.sub(r"[\"“”'`´]", "", normalizar(p)).strip(" .-")
    t = RE_SOCIEDAD.sub("", t).strip(" .,-")
    return re.sub(r"\s+", " ", t)


def adjudicaciones(texto: str) -> list:
    """[{proveedor, proveedor_n, monto, fecha, modalidad, extracto}] de una página. Si no hay monto en pesos, no se toma."""
    tn = normalizar(texto)
    out = []
    for m in RE_ADJ.finditer(tn):
        prov = re.sub(r"\s+", " ", texto[m.start(1):m.end(1)]).strip(" .,;:-\"“”")
        if len(prov) < 3 or re.match(r"(?i)^(la|el|los|las|dicha|esta|misma)\b", prov):
            continue
        mm = RE_PESOS.search(texto[m.end(1):m.end(1) + 500])
        if not mm:
            continue
        monto = _monto(mm.group(1))
        if not monto or monto < 1000:
            continue
        ventana = tn[max(0, m.start() - 800):m.end() + 600]
        mod = RE_MODALIDAD.search(ventana)
        out.append({"proveedor": prov[:120], "proveedor_n": normalizar_proveedor(prov)[:120], "monto": round(monto, 2),
                    "fecha": fecha_cerca(tn, m.start()), "modalidad": mod.group(0) if mod else None,
                    "extracto": re.sub(r"\s+", " ", texto[max(0, m.start() - 120):m.end(1) + 260]).strip()[:500]})
    return out
