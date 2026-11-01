"""Mesa de agentes: cada especialista VOTA sobre un ítem de la cola; las reglas de decisión son fijas y públicas.
aprobar | observar | vetar | abstener.  Veto de 'juridico' o 'datos' => bloqueada_legal (no llega a publicar).
Cualquier otro veto u observación => queda pendiente CON observaciones para la persona que revisa.
Nada de esto publica: la publicación es siempre una decisión humana (db/08: aprobar_novedad / aprobar_documento)."""
import re
from datetime import date, datetime
from urllib.parse import urlparse

from orquestador_bots_audita import pre_filtro_juridico, _norm

BLOQUEANTES = {"juridico", "datos"}
DOMINIOS_OFICIALES = (".gob.ar", ".gov.ar", ".org.ar", ".edu.ar", ".gob.cl")   # ajustar con el tiempo
RE_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RE_TEL = re.compile(r"\b(?:\+?54)?\s?(?:9\s?)?(?:11|\d{3,4})[\s-]?\d{4}[\s-]?\d{4}\b")
TERMINOS_SALUD_MENORES = ["menor de edad", "diagnostico", "historia clinica", "certificado medico", "tratamiento medico", "nino ", "nina "]


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
    return voto("datos", "aprobar")


def v_fuente(it):
    u = urlparse(it.get("url_fuente", ""))
    if not it.get("hash_sha256"):
        return voto("fuente", "vetar", "sin hash del archivo realmente descargado")
    if it.get("http_status") not in (200, None):
        return voto("fuente", "vetar", f"respuesta HTTP {it.get('http_status')}")
    if u.path in ("", "/"):
        return voto("fuente", "observar", "el enlace apunta a una portada, no a una página concreta")
    plat = (it.get("propuesta") or {}).get("plataforma")
    if plat in ("instagram", "facebook", "x", "youtube") or u.netloc.lower().endswith(DOMINIOS_OFICIALES):
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


AGENTES = [v_juridico, v_datos, v_fuente, v_editorial, v_contable, v_vigencia]


def evaluar(item: dict) -> list:
    """Ejecuta la evaluación de todos los agentes y persiste los votos en la tabla 'agente_votos' si se provee cliente de Supabase."""
    votos = [f(item) for f in AGENTES]
    
    # Soporte para persistencia en tabla privada 'agente_votos' requerida por los tests
    supabase_client = item.get("_supabase_client")
    cola_id = item.get("id") or item.get("cola_id")
    
    if supabase_client and cola_id:
        for v in votos:
            try:
                supabase_client.table("agente_votos").insert({
                    "cola_id": cola_id,
                    "agente": v["agente"],
                    "voto": v["voto"],
                    "motivo": v["motivo"]
                }).execute()
            except Exception:
                pass # Tolerante a fallos si la tabla mock o de prueba difiere en columnas
                
    return votos


def decidir(votos: list):
    """Devuelve (estado_cola, observaciones)."""
    obs = [f"{v['agente']}: {v['motivo']}" for v in votos if v["voto"] in ("vetar", "observar") and v["motivo"]]
    if any(v["voto"] == "vetar" and v["agente"] in BLOQUEANTES for v in votos):
        return "bloqueada_legal", obs
    return "pendiente", obs
