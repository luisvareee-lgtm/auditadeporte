"""Lector de reportes de ejecución presupuestaria del sistema RAFAM (el que usan los municipios bonaerenses).

Reconoce el tipo de reporte (gastos o recursos), la clasificación (por finalidad y función, por carácter económico,
por estructura programática, por objeto), el período y cada línea con sus columnas. Después hace controles
OBJETIVOS de aritmética y de crédito. No opina: marca lo que hay que verificar y explica por qué.

Columnas de gastos (10): crédito aprobado, modificaciones, crédito vigente, preventivo, compromiso, devengado,
pagado, crédito disponible, vigente - devengado, devengado no pagado.
Columnas de recursos (8): estimado, modificaciones, vigente, devengado, vigente - devengado, percibido,
devengado - percibido, vigente - percibido.
"""
import re
import shutil
import subprocess
import tempfile

COL_GASTOS = ["aprobado", "modificaciones", "vigente", "preventivo", "compromiso", "devengado", "pagado",
              "disponible", "vigente_menos_devengado", "devengado_no_pagado"]
COL_RECURSOS = ["estimado", "modificaciones", "vigente", "devengado", "vigente_menos_devengado", "percibido",
                "devengado_menos_percibido", "vigente_menos_percibido"]
# los reportes mezclan 1.234,56 con 1,234.56 en la última columna; también vienen números pegados entre sí
# que no empiece en medio de otro número o de un código (17.2.01.51), salvo números pegados ("…,17124.418…")
_B = r"(?:(?<![\d.,\-])|(?<=,\d\d))"
NUM = re.compile(_B + r"-?\d{1,3}(?:,\d{3})+\.\d{2}(?!\d)|" +          # 1,234,567.89 (va primero)
                 _B + r"-?\d{1,3}(?:\.\d{3})*,\d{2}(?!,)|" +           # 1.234.567,89 (admite otro número pegado detrás)
                 _B + r"-?\d+,\d{2}(?!,)|" + _B + r"-?\d{1,3}\.\d{2}(?![\d.,])")
RE_PERIODO = re.compile(r"Del\s+(\d{2})/(\d{2})/(\d{4})\s+al\s+(\d{2})/(\d{2})/(\d{4})")
RE_EJERCICIO = re.compile(r"Ejercicio:\s*(\d{4})")
TOL = 1.0
UMBRAL_GRAVE = 1_000_000_000          # $ 1.000 millones


def _valor(s: str) -> float:
    if re.search(r",\d{2}$", s):
        return float(s.replace(".", "").replace(",", "."))
    return float(s.replace(",", ""))


def pesos(v: float) -> str:
    return "$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def texto_layout(pdf: bytes):
    """Texto respetando columnas (pdftotext -layout). None si no está poppler."""
    if not shutil.which("pdftotext"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf); f.flush()
        r = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=120)
        return r.stdout.decode("utf-8", "ignore") if r.returncode == 0 else None


def detectar(texto: str):
    """{'tipo', 'clasificacion', 'ejercicio', 'desde', 'hasta'} o None si no es un reporte de ejecución RAFAM."""
    cab = texto[:4000].upper()
    if "R.A.F.A.M" not in cab or "EJECUCI" not in cab:
        return None
    tipo = "recursos" if "RECURSOS" in cab[:1500] else "gastos" if "GASTOS" in cab[:1500] else None
    if not tipo:
        return None
    if "FINALIDAD" in cab:
        clas = "finalidad_funcion"
    elif "CARACTER ECON" in cab or "CARÁCTER ECON" in cab:
        clas = "caracter_economico"
    elif "PROGRAM" in cab or "JURISDICCI" in cab:
        clas = "estructura_programatica"
    elif "OBJETO" in cab:
        clas = "objeto_del_gasto"
    else:
        clas = "rubro" if tipo == "recursos" else "otra"
    m = RE_PERIODO.search(texto[:4000]); e = RE_EJERCICIO.search(texto[:6000])
    desde = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
    hasta = f"{m.group(6)}-{m.group(5)}-{m.group(4)}" if m else None
    return {"tipo": tipo, "clasificacion": clas, "ejercicio": int(e.group(1)) if e else (int(m.group(6)) if m else None),
            "desde": desde, "hasta": hasta}


def filas(texto: str, tipo: str) -> list:
    n = 10 if tipo == "gastos" else 8
    cols = COL_GASTOS if tipo == "gastos" else COL_RECURSOS
    out = []
    lineas = texto.splitlines()
    for i, ln in enumerate(lineas):
        nums = NUM.findall(ln)
        if len(nums) != n:
            continue
        desc = re.sub(r"\s+", " ", ln[:NUM.search(ln).start()]).strip(" :")
        # descripciones largas siguen en la línea de abajo ("Subsidio Apoyo Sostenimiento a / Instituciones Deportivas")
        sig = lineas[i + 1] if i + 1 < len(lineas) else ""
        if tipo == "recursos" and not es_total(desc) and sig.strip() and not NUM.search(sig) and not re.search(r"R\.A\.F\.A\.M|Filtro|Hoja", sig):
            resto = re.sub(r"\s{2,}.*$", "", sig.strip())
            resto = re.sub(r"\b(Afectados|libre disponibilidad)\b", "", resto).strip()
            if resto and not re.match(r"^\d{1,2}\.\d", resto):
                desc = f"{desc} {resto}"
        if not desc:
            continue
        out.append({"descripcion": desc[:120], **{c: _valor(v) for c, v in zip(cols, nums)}})
    return out


def es_total(d: str) -> bool:
    return bool(re.match(r"(?i)^(total|totales)\b", d))


def controlar_gastos(fs: list) -> dict:
    cierre, credito = [], []
    for f in fs:
        d = f["descripcion"]
        if abs(f["aprobado"] + f["modificaciones"] - f["vigente"]) > TOL:
            cierre.append(f"{d}: el crédito vigente no es aprobado + modificaciones")
        if abs(f["vigente"] - f["preventivo"] - f["compromiso"] - f["disponible"]) > TOL:
            cierre.append(f"{d}: el crédito disponible no cierra")
        if abs(f["devengado"] - f["pagado"] - f["devengado_no_pagado"]) > TOL:
            cierre.append(f"{d}: el devengado no pagado no cierra")
        if f["pagado"] - f["devengado"] > TOL:
            cierre.append(f"{d}: lo pagado supera lo devengado")
        if es_total(d):
            continue                                   # los totales repiten lo de sus líneas
        exceso = f["preventivo"] + f["compromiso"] - f["vigente"]
        sin_credito = f["vigente"] == 0 and (f["compromiso"] or f["devengado"])
        if exceso > TOL or sin_credito:
            credito.append({"linea": d, "vigente": f["vigente"], "reservado": f["preventivo"], "comprometido": f["compromiso"],
                            "devengado": f["devengado"], "exceso": round(max(exceso, 0), 2), "sin_credito": bool(sin_credito),
                            "devengado_sobre_credito": round(max(f["devengado"] - f["vigente"], 0), 2)})
    credito.sort(key=lambda x: -x["exceso"])
    hojas = [f for f in fs if not es_total(f["descripcion"])]
    tot = next((f for f in reversed(fs) if re.match(r"(?i)^(totales? generales?|total gastos)$", f["descripcion"])), None)
    suma_ok = None
    if tot and hojas and all(re.match(r"^\d{3} ", f["descripcion"]) for f in hojas):
        suma_ok = all(abs(sum(h[c] for h in hojas) - tot[c]) <= 1 + len(hojas) * 0.01 for c in COL_GASTOS)
    return {"cierre": cierre, "credito": credito, "suma_lineas_igual_total": suma_ok,
            "totales": {c: tot[c] for c in COL_GASTOS} if tot else None}


def linea_deporte(fs: list):
    """La función 346 'Deporte y recreación' (clasificación por finalidad y función)."""
    f = next((x for x in fs if re.match(r"^346\b", x["descripcion"]) or re.search(r"(?i)deporte", x["descripcion"])), None)
    if not f:
        return None
    pct = round(100 * f["devengado"] / f["vigente"], 1) if f.get("vigente") else None
    return {"linea": f["descripcion"], "aprobado": f["aprobado"], "vigente": f["vigente"], "comprometido": f["compromiso"],
            "devengado": f["devengado"], "pagado": f["pagado"], "porcentaje_devengado": pct}


def analizar(texto: str):
    info = detectar(texto)
    if not info:
        return None
    fs = filas(texto, info["tipo"])
    res = {**info, "lineas": len(fs), "filas": fs}
    if info["tipo"] == "gastos":
        res.update(controlar_gastos(fs))
        res["deporte"] = linea_deporte(fs) if info["clasificacion"] in ("finalidad_funcion", "estructura_programatica") else None
        if res.get("totales") and res["deporte"] and res["totales"].get("aprobado"):
            res["deporte"]["peso_en_presupuesto"] = round(100 * res["deporte"]["aprobado"] / res["totales"]["aprobado"], 3)
            res["deporte"]["porcentaje_devengado_municipio"] = round(100 * res["totales"]["devengado"] / res["totales"]["vigente"], 1) \
                if res["totales"].get("vigente") else None
    else:
        tot = next((f for f in reversed(fs) if re.match(r"(?i)^total general", f["descripcion"])), None)
        res["totales"] = {c: tot[c] for c in COL_RECURSOS} if tot else None
        res["deporte_recursos"] = [f for f in fs if re.search(r"(?i)deport|juegos bonaer", f["descripcion"])]
    return res


def registrar(cli, juris: str, url: str, sha256: str, titulo: str, pdf: bytes):
    """Si el PDF es un reporte de ejecución RAFAM, lo guarda leído en ejecuciones_presupuestarias. Devuelve el análisis o None."""
    texto = texto_layout(pdf)
    if not texto:
        return None
    r = analizar(texto)
    if not r or not juris:
        return r
    fila = {"juris_slug": juris, "url": url, "sha256": sha256, "titulo": (titulo or "")[:200], "tipo": r["tipo"],
            "clasificacion": r["clasificacion"], "ejercicio": r.get("ejercicio"), "desde": r.get("desde"), "hasta": r.get("hasta"),
            "totales": r.get("totales"), "deporte": r.get("deporte"), "deporte_recursos": r.get("deporte_recursos"),
            "credito": r.get("credito") or [], "cierre": r.get("cierre") or [], "lineas": r["lineas"], "filas": r["filas"][:600]}
    try:
        cli.table("ejecuciones_presupuestarias").upsert([fila], on_conflict="sha256").execute()
    except Exception as e:                  # sin db/20 todavía
        print(f"  rafam: no se pudo guardar ({str(e)[:100]})", flush=True)
    return r
