"""Carga el catálogo de fuentes oficiales por jurisdicción (bot/catalogo_fuentes.json) en la base.

* Cada municipio y cada provincia queda como una institución (slug muni-… / prov-…, ámbito "municipio" u "otro").
* Sus fuentes (boletín oficial, transparencia, concejo, compras, presupuesto) se cargan en fuentes_monitoreadas:
  el orquestador las recorre en su ciclo normal, respetando robots.txt.
* Qué jurisdicciones corresponden a cada club queda en el mismo JSON ("clubes"): lo usan el contraste de
  colectas y la búsqueda de respaldos.
Solo agrega o actualiza: no borra nada. Uso: python cargar_fuentes.py [--prueba]
"""
import json
import os
import sys

import orquestador_bots_audita as o

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogo_fuentes.json")
TIPOS = {"boletin_oficial", "portal_transparencia", "igj", "compras", "concejo_deliberante", "sitio_oficial", "red_oficial", "otro"}
PORTALES = {"presupuesto_abierto", "comprar", "boletin_oficial_nacional", "boletin_municipal", "sitio_oficial", "red_social_oficial", "otro"}


def catalogo():
    with open(RUTA, encoding="utf-8") as fh:
        return json.load(fh)


def jurisdicciones_de(club_slug: str) -> list:
    """Slugs de las instituciones-jurisdicción de un club (municipio, provincia). Vacío si no está en el catálogo."""
    try:
        return catalogo().get("clubes", {}).get(club_slug, [])
    except FileNotFoundError:
        return []


def validar(cat: dict) -> list:
    errores = []
    for slug, j in cat["jurisdicciones"].items():
        if not (slug.startswith("muni-") or slug.startswith("prov-") or slug.startswith("nac-")):
            errores.append(f"{slug}: el slug tiene que empezar con muni-, prov- o nac-")
        for f in j.get("fuentes", []):
            if f["tipo"] not in TIPOS:
                errores.append(f"{slug}: tipo inválido {f['tipo']}")
            if f.get("portal_origen", "sitio_oficial") not in PORTALES:
                errores.append(f"{slug}: portal inválido {f.get('portal_origen')}")
            if not f["url"].startswith("https://") and not f["url"].startswith("http://"):
                errores.append(f"{slug}: url inválida {f['url']}")
    for club, js in cat.get("clubes", {}).items():
        for j in js:
            if j not in cat["jurisdicciones"]:
                errores.append(f"club {club}: jurisdicción {j} no existe en el catálogo")
    return errores


def main():
    cat = catalogo()
    err = validar(cat)
    if err:
        raise SystemExit("Catálogo con errores:\n" + "\n".join(err))
    prueba = "--prueba" in sys.argv
    clubes = {c["slug"] for c in o.db().table("clubes").select("slug").execute().data or []}
    faltan = sorted(set(cat.get("clubes", {})) - clubes)
    if faltan:
        print("Aviso: clubes del catálogo que no están en la base:", faltan)
    n_inst = n_fu = 0
    for slug, j in cat["jurisdicciones"].items():
        fila = {"slug": slug, "sigla": j.get("sigla") or slug.split("-", 1)[1][:12].upper(), "nombre": j["nombre"],
                "ambito": "municipio" if slug.startswith("muni-") else "otro", "sitio_web": j.get("sitio_web")}
        if prueba:
            print("institución", fila)
        else:
            o.db().table("instituciones").upsert(fila, on_conflict="slug").execute()
        n_inst += 1
    ids = {} if prueba else {i["slug"]: i["id"] for i in o.db().table("instituciones").select("id,slug").execute().data or []}
    for slug, j in cat["jurisdicciones"].items():
        for f in j.get("fuentes", []):
            fila = {"institucion_id": ids.get(slug), "nombre": f["nombre"][:200], "url": f["url"], "tipo": f["tipo"],
                    "portal_origen": f.get("portal_origen", "sitio_oficial"), "frecuencia_dias": f.get("frecuencia_dias", 7),
                    "usa_sitemap": f.get("usa_sitemap", False), "sitemap_url": f.get("sitemap_url"),
                    "patron_url": f.get("patron_url"), "responsable_auditoria": "catalogo_fuentes",
                    "nota": f.get("nota")}
            if prueba:
                print("  fuente", slug, fila["tipo"], fila["url"])
            else:
                o.db().table("fuentes_monitoreadas").upsert(fila, on_conflict="url").execute()
            n_fu += 1
    print(f"{'(prueba) ' if prueba else ''}jurisdicciones: {n_inst} · fuentes: {n_fu} · clubes con jurisdicción: {len(cat.get('clubes', {}))}")


if __name__ == "__main__":
    main()
