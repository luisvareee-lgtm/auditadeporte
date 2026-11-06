"""Arma datos/transparencia.json: el resumen público, en lenguaje simple, de qué publica cada jurisdicción.

Solo datos agregados y públicos: nombres de municipios/provincias, sus páginas oficiales, si respondieron,
cuántos documentos leyeron los agentes y cuántos se encontraron sobre deporte adaptado. Nada personal.
El estado de cada jurisdicción es un HECHO verificable, sin calificativos:
  publica     -> tiene un boletín oficial u otra fuente oficial que se pudo leer en la última revisión
  a_medias    -> publica algo (compras, presupuesto) pero no su boletín, o algunas páginas no responden
  no_publica  -> no se encontró publicación revisable (bloquea la consulta, falla técnica o no existe)
Uso: python generar_resumen.py [--salida ruta]
"""
import json
import os
import sys
from datetime import datetime, timezone

import orquestador_bots_audita as o
from cargar_fuentes import catalogo

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "..", "datos", "transparencia.json")
TIPO_SIMPLE = {"boletin_oficial": "Boletín oficial", "compras": "Compras y licitaciones", "portal_transparencia": "Transparencia y presupuesto",
               "concejo_deliberante": "Concejo Deliberante", "sitio_oficial": "Sitio oficial", "otro": "Datos oficiales", "igj": "Registro de entidades"}


def motivo_simple(pendiente: str, provincia: str) -> str:
    p = (pendiente or "").lower()
    if "no ser leído" in p or "robots" in p:
        m = "Su sitio oficial no permite revisar los documentos de forma automática."
    elif "certificado" in p:
        m = "Su sitio oficial tiene una falla de seguridad que impide consultarlo de forma segura."
    elif "401" in p or "autentic" in p:
        m = "Pide usuario y contraseña para consultar el boletín oficial."
    elif "403" in p:
        m = "Rechaza la consulta automática de su boletín oficial."
    elif "no se encontró" in p or "pdf mensual" in p:
        m = "No encontramos un boletín oficial ni un portal de transparencia que se pueda revisar."
    else:
        m = "No encontramos publicación oficial que se pueda revisar."
    if "sibom" in p:
        m += " Parte de sus normas pueden aparecer en el sistema de boletines municipales de la Provincia (SIBOM)."
    return m


# Lo que una jurisdicción debería tener publicado para que se pueda seguir la plata del deporte adaptado.
# Cada ítem queda: completo (hay fuente oficial que se pudo leer), parcial (existe pero no respondió o está
# desactualizada) o no_encontrado (no hallamos una publicación revisable). Es un hecho verificable, no una nota.
ITEMS_CHECKLIST = [
    ("boletin", "Boletín oficial con decretos y resoluciones", ("boletin_oficial",)),
    ("compras", "Compras y licitaciones", ("compras",)),
    ("presupuesto", "Presupuesto y su ejecución", ("portal_transparencia",)),
    ("normas", "Ordenanzas del Concejo Deliberante", ("concejo_deliberante",)),
]


def checklist(slug: str, fs: list, encontrados: int, publicados: int) -> list:
    out = []
    for clave, texto, tipos in ITEMS_CHECKLIST:
        if clave == "normas" and not slug.startswith("muni-"):
            continue
        propias = [f for f in fs if f.get("tipo") in tipos]
        if any(f.get("estado") == "activa" and f.get("ultimo_status") == 200 and "solo hasta" not in (f.get("nota") or "")
               for f in propias):
            estado = "completo"
        elif propias:
            estado = "parcial"
        else:
            estado = "no_encontrado"
        out.append({"clave": clave, "texto": texto, "estado": estado})
    out.append({"clave": "deporte_adaptado", "texto": "Documentos sobre deporte adaptado",
                "estado": "completo" if publicados else ("parcial" if encontrados else "no_encontrado")})
    return out


def tipo_juris(slug: str) -> str:
    if slug.startswith("muni-"):
        return "municipio"
    if slug == "nac-uncuyo":
        return "universidad"
    return "nacion" if slug.startswith("nac-") else "provincia"


def pedido(slug: str, juris_de_club: list, marco: dict) -> dict:
    """Base legal para pedir información a esa jurisdicción (para el texto del pedido)."""
    t = tipo_juris(slug)
    if t == "municipio":
        prov = next((j for j in juris_de_club if j.startswith("prov-")), None)
        m = dict(marco["municipio"])
        if prov and prov in marco:
            m["provincial"] = f"{marco[prov]['norma']} ({marco[prov]['alcance']})"
        if prov == "prov-buenos-aires":
            m["extra"] = marco["municipio_pba"]["extra"]
    elif t == "universidad":
        m = dict(marco["nac-nacion"])
    else:
        m = dict(marco.get(slug) or marco["municipio"])
    m["base"] = marco["base_constitucional"]
    return m


def construir(db=None, cat=None, marco=None) -> dict:
    db = db or o.db()
    cat = cat or catalogo()
    marco = marco or json.load(open(os.path.join(AQUI, "marco_legal.json"), encoding="utf-8"))
    insts = {i["slug"]: i for i in db.table("instituciones").select("id,slug,nombre,sitio_web").execute().data or []}
    fuentes = db.table("fuentes_monitoreadas").select("id,institucion_id,club_id,nombre,url,tipo,estado,ultimo_status,ultima_revision,nota,fallos_consecutivos") \
        .execute().data or []
    vistas = db.table("fuente_urls_vistas").select("fuente_id").execute().data or []
    leidos_por_fuente = {}
    for v in vistas:
        leidos_por_fuente[v["fuente_id"]] = leidos_por_fuente.get(v["fuente_id"], 0) + 1
    cola = db.table("cola_revision").select("agente,estado,revisada_por,propuesta,club_id,institucion_id") \
        .eq("agente", "rastreador").execute().data or []
    clubes = {c["slug"]: c for c in db.table("clubes").select("id,slug,nombre,publicado").execute().data or []
              if c.get("publicado") is not False}
    docs = db.table("documentos_fuente").select("institucion_id,club_id,publicado").execute().data or []

    juris_por_club = cat.get("clubes", {})
    clubes_por_juris = {}
    for club_slug, js in juris_por_club.items():
        if club_slug in clubes:
            for j in js:
                clubes_por_juris.setdefault(j, []).append(clubes[club_slug])

    salida = []
    for slug, j in cat["jurisdicciones"].items():
        inst = insts.get(slug) or {}
        fs = [f for f in fuentes if inst and f.get("institucion_id") == inst.get("id")]
        ok = [f for f in fs if f.get("estado") == "activa" and f.get("ultimo_status") == 200]
        boletin_ok = [f for f in ok if f["tipo"] == "boletin_oficial"]
        notas = " ".join((f.get("nota") or "") for f in fs)
        if not fs:
            estado, motivo = "no_publica", motivo_simple(j.get("pendiente"), "")
        elif not ok and max((f.get("fallos_consecutivos") or 0) for f in fs) < 3:
            # una caída puntual no alcanza para decir que no publica: se espera a tres fallas seguidas
            estado, motivo = "a_medias", "Su página oficial no respondió en la última revisión. Se vuelve a intentar todos los días."
        elif not ok:
            estado, motivo = "no_publica", "Sus páginas oficiales no respondieron en las últimas revisiones (tres o más intentos seguidos)."
        elif "solo hasta" in notas:
            estado, motivo = "a_medias", "Publica su boletín oficial, pero la página muestra ediciones viejas: " + notas.split("lista ediciones por año ")[-1].rstrip(".") + "."
        elif not boletin_ok and slug.startswith("muni-"):
            estado, motivo = "a_medias", "Publica información (compras, presupuesto o transparencia), pero no encontramos su boletín oficial revisable."
        elif len(ok) < len(fs):
            estado, motivo = "a_medias", "Publica datos, pero algunas de sus páginas oficiales no respondieron en la última revisión."
        else:
            estado, motivo = "publica", "Publica documentos oficiales que se pueden revisar."
        ids_fuentes = {f["id"] for f in fs}
        clubes_j = clubes_por_juris.get(slug, [])
        ids_clubes = {c["id"] for c in clubes_j}
        encontrados = sum(1 for c in cola if (c.get("propuesta") or {}).get("fuente_id") in ids_fuentes
                          and (c.get("propuesta") or {}).get("indice") and c.get("revisada_por") != "limpieza automática"
                          and c.get("estado") != "rechazada")
        publicados = sum(1 for d in docs if d.get("publicado") and
                         (d.get("institucion_id") == inst.get("id") or (slug.startswith("muni-") and d.get("club_id") in ids_clubes)))
        juris_de_un_club = next((juris_por_club[c["slug"]] for c in clubes_j), [])
        revs = [f["ultima_revision"] for f in fs if f.get("ultima_revision")]
        salida.append({
            "slug": slug, "nombre": inst.get("nombre") or j["nombre"], "tipo": tipo_juris(slug),
            "clubes": sorted(c["nombre"] for c in clubes_j), "estado": estado, "motivo": motivo,
            "sitio_web": inst.get("sitio_web") or j.get("sitio_web"),
            "fuentes": [{"nombre": f["nombre"], "url": f["url"], "tipo": TIPO_SIMPLE.get(f["tipo"], "Datos oficiales"),
                         "responde": f.get("estado") == "activa" and f.get("ultimo_status") == 200} for f in fs],
            "documentos_leidos": sum(leidos_por_fuente.get(i, 0) for i in ids_fuentes),
            "encontrados_para_revisar": encontrados, "publicados": publicados,
            "ultima_revision": max(revs)[:10] if revs else None,
            "checklist": checklist(slug, fs, encontrados, publicados),
            "pedido": pedido(slug, juris_de_un_club, marco),
        })
    orden = {"municipio": 0, "provincia": 1, "universidad": 2, "nacion": 3}
    salida.sort(key=lambda x: (orden[x["tipo"]], x["nombre"]))
    tot = {e: sum(1 for x in salida if x["estado"] == e) for e in ("publica", "a_medias", "no_publica")}
    return {
        "actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "totales": {**tot, "jurisdicciones": len(salida), "clubes": len(clubes),
                    "documentos_leidos": sum(x["documentos_leidos"] for x in salida),
                    "encontrados_para_revisar": sum(x["encontrados_para_revisar"] for x in salida),
                    "publicados": sum(x["publicados"] for x in salida)},
        "fuente_marco_legal": marco.get("_fuente"),
        "jurisdicciones": salida,
    }


def main():
    ruta = sys.argv[sys.argv.index("--salida") + 1] if "--salida" in sys.argv else SALIDA
    datos = construir()
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = json.dumps(datos, ensure_ascii=False, indent=1)
    viejo = open(ruta, encoding="utf-8").read() if os.path.exists(ruta) else ""
    # solo se reescribe si cambió algo más que la fecha
    sin_fecha = lambda t: "\n".join(l for l in t.splitlines() if '"actualizado"' not in l)
    if sin_fecha(nuevo) != sin_fecha(viejo):
        open(ruta, "w", encoding="utf-8").write(nuevo + "\n")
        print("resumen actualizado:", ruta)
    else:
        print("sin cambios")
    print(json.dumps(datos["totales"], ensure_ascii=False))


if __name__ == "__main__":
    main()
