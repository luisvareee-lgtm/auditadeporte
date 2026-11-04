"""Mesa de agentes v6: cada especialista VOTA sobre un ítem de la cola; las reglas de decisión son fijas y públicas.
aprobar | observar | vetar | abstener.  Veto de 'juridico', 'datos' o 'alcance' => bloqueada_legal (no se publica;
una persona puede reabrirlo desde el panel dejando la razón escrita). Cualquier otro veto u observación =>
queda pendiente CON observaciones para la persona que revisa. Nada de esto publica: decide siempre una persona."""
import re
from datetime import date, datetime
from urllib.parse import urlparse

from orquestador_bots_audita import pre_filtro_juridico, _norm

BLOQUEANTES = {"juridico", "datos", "alcance"}
DOMINIOS_OFICIALES = (".gob.ar", ".gov.ar", ".org.ar", ".edu.ar", ".gob.cl", "basquetadaptado.com.ar")   # ajustar con el tiempo
RE_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RE_TEL = re.compile(r"\b(?:\+?54)?\s?(?:9\s?)?(?:11|\d{3,4})[\s-]?\d{4}[\s-]?\d{4}\b")
TERMINOS_SALUD_MENORES = ["menor de edad", "diagnostico", "historia clinica", "certificado medico", "tratamiento medico", "nino ", "nina "]
# Única lista de acciones que un especialista puede proponer (la base vuelve a controlarla al aprobar).
ACCIONES_PERMITIDAS = {"borrador_pliego_rse", "marcar_no_vigente", "reclamar_pedido", "pausar_fuente",
                       "purgar_contactos", "solo_informativa"}
JERGA = ["devengado", "erogacion", "imputacion presupuestaria", "partida presupuestaria", "considerando",
         "visto el expediente", "a saber", "en virtud de", "conforme lo normado"]


def voto(agente, v, motivo=""):
    return {"agente": agente, "voto": v, "motivo": motivo}


def v_juridico(it):
    motivos = [m for m in pre_filtro_juridico(it.get("texto", "") + " " + it.get("titulo", ""), it.get("url_fuente", ""))
               if not m.startswith("posible_dato_personal")]
    return voto("juridico", "vetar", "; ".join(motivos)) if motivos else voto("juridico", "aprobar")


def v_datos(it):
    t = f"{it.get('texto', '')} {it.get('titulo', '')}"
    pre = [m for m in pre_filtro_juridico(t, it.get("url_fuente", "")) if m.startswith("posible_dato_personal")]
    if pre:
        return voto("datos", "vetar", "DNI/CUIL en el texto")
    n = _norm(t)
    if any(x in n for x in TERMINOS_SALUD_MENORES):
        return voto("datos", "vetar", "posible dato de salud o de menores")
    if RE_MAIL.search(t) or RE_TEL.search(t):
        return voto("datos", "observar", "contacto personal en el texto: revisar si debe tacharse")
    ind = (it.get("propuesta") or {}).get("indicadores") or {}
    if ind.get("contiene_posibles_dni"):
        return voto("datos", "observar", "el documento tiene números con forma de DNI/CUIL: el resumen no debe repetirlos")
    return voto("datos", "aprobar")


def v_fuente(it):
    if not it.get("hash_sha256"):
        return voto("fuente", "vetar", "sin hash del archivo realmente descargado")
    if it.get("http_status") not in (200, None):
        return voto("fuente", "vetar", f"respuesta HTTP {it.get('http_status')}")
    p = it.get("propuesta") or {}
    if it.get("tipo") == "propuesta_cambio":
        return voto("fuente", "aprobar")
    if p.get("requiere_ocr_o_revision_humana"):
        return voto("fuente", "observar", f"sin texto legible ({p.get('motivo_revision')}): leerlo a mano antes de resumir")
    u = urlparse(it.get("url_fuente", ""))
    if u.path in ("", "/"):
        return voto("fuente", "observar", "el enlace apunta a una portada, no a una página concreta")
    if p.get("fuente_id"):
        return voto("fuente", "aprobar", "fuente registrada por la administración")
    if p.get("plataforma") in ("instagram", "facebook", "x", "youtube") or u.netloc.lower().endswith(DOMINIOS_OFICIALES):
        return voto("fuente", "aprobar")
    return voto("fuente", "observar", "dominio no reconocido como oficial: confirmar a mano")


def v_editorial(it):
    if it.get("tipo") != "novedad_red":
        return voto("editorial", "abstener")
    ext = (it.get("propuesta") or {}).get("extracto", "")
    if not ext or len(ext) > 280:
        return voto("editorial", "vetar", "extracto vacío o de más de 280 caracteres")
    letras = [c for c in ext if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) > 0.6 and len(letras) > 15:
        return voto("editorial", "observar", "texto en mayúsculas: cita textual, no reescribir")
    return voto("editorial", "aprobar")


def v_contable(it):
    p = it.get("propuesta") or {}
    items, total = p.get("items"), p.get("total")
    if not items or total is None:
        return voto("contable", "abstener")
    montos = [float(i.get("monto", 0)) for i in items]
    if any(m < 0 for m in montos):
        return voto("contable", "observar", "hay montos negativos")
    if abs(sum(montos) - float(total)) > 0.01:
        return voto("contable", "vetar", f"los ítems suman {sum(montos):.2f} y el total declarado es {float(total):.2f}")
    return voto("contable", "aprobar")


def v_vigencia(it, hoy=None):
    f = (it.get("propuesta") or {}).get("fecha_posteo")
    if not f:
        return voto("vigencia", "abstener")
    try:
        d = datetime.strptime(f, "%Y-%m-%d").date()
    except ValueError:
        return voto("vigencia", "vetar", "fecha con formato inválido")
    dias = ((hoy or date.today()) - d).days
    if dias < 0:
        return voto("vigencia", "vetar", "fecha futura")
    return voto("vigencia", "observar", f"dato de hace {dias} días") if dias > 365 else voto("vigencia", "aprobar")


def v_alcance(it):
    """Los especialistas solo pueden proponer acciones de la lista cerrada."""
    if it.get("tipo") != "propuesta_cambio":
        return voto("alcance", "abstener")
    acc = (it.get("propuesta") or {}).get("accion")
    if acc not in ACCIONES_PERMITIDAS:
        return voto("alcance", "vetar", f"acción fuera de la lista permitida: {acc}")
    return voto("alcance", "aprobar")


def v_lectura(it):
    """Lectura fácil: textos que se mostrarán o enviarán (borradores de reclamo, descripciones de pliego)."""
    p = it.get("propuesta") or {}
    t = p.get("borrador_texto") or (p.get("parametros") or {}).get("descripcion")
    if not t:
        return voto("lectura", "abstener")
    frases = [f for f in re.split(r"[.!?;]\s+", t) if f.strip()]
    largas = [f for f in frases if len(f.split()) > 35]
    jerga = [j for j in JERGA if j in _norm(t)]
    if largas or jerga:
        partes = ([f"{len(largas)} frase(s) de más de 35 palabras"] if largas else []) + ([f"jerga: {', '.join(jerga)}"] if jerga else [])
        return voto("lectura", "observar", "simplificar: " + "; ".join(partes))
    return voto("lectura", "aprobar")


AGENTES = [v_juridico, v_datos, v_fuente, v_editorial, v_contable, v_vigencia, v_alcance, v_lectura]


def evaluar(item: dict) -> list:
    return [f(item) for f in AGENTES]


def decidir(votos: list):
    """Devuelve (estado_cola, observaciones)."""
    obs = [f"{v['agente']}: {v['motivo']}" for v in votos if v["voto"] in ("vetar", "observar") and v["motivo"]]
    if any(v["voto"] == "vetar" and v["agente"] in BLOQUEANTES for v in votos):
        return "bloqueada_legal", obs
    return "pendiente", obs
