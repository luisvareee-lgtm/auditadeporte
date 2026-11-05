"""Limpieza puntual de la cola: retira (no borra) ítems de agentes que quedaron como ruido.
  1) Portadas de índices (boletines, compras, transparencia, concejo) propuestas por el rastreador:
     ahora se buscan los documentos de adentro.
  2) Duplicados del rastreador sobre la misma URL: queda el más nuevo.
  3) Avisos de vigencia repetidos sobre la misma autoridad: queda el más nuevo; si la autoridad ya no está
     vigente, se retira también el último.
Cada ítem retirado queda 'rechazada' con motivo, quién y cuándo. Uso: python limpieza_cola.py [--prueba]"""
import sys

import orquestador_bots_audita as o

QUIEN = "limpieza automática"


def retirar(item, motivo, nota, prueba):
    if prueba:
        print(f"  [prueba] retiraría ({motivo}): {item['titulo'][:90]}")
        return
    o.db().table("cola_revision").update({"estado": "rechazada", "motivo_codigo": motivo, "revisada_por": QUIEN,
                                          "revisada_en": o.ahora().isoformat(), "nota_revision": nota}).eq("id", item["id"]).execute()


def main():
    prueba = "--prueba" in sys.argv
    cola = o.db().table("cola_revision").select("id,agente,tipo,titulo,url_fuente,propuesta,creado_en,estado") \
        .eq("estado", "pendiente").execute().data or []
    fuentes = o.db().table("fuentes_monitoreadas").select("url,tipo").execute().data or []
    indices = {f["url"].rstrip("/") for f in fuentes if f["tipo"] in o.TIPOS_INDICE}
    vigentes = {a["id"] for a in o.db().table("autoridades").select("id").eq("vigente", True).execute().data or []}
    n = {"portada_indice": 0, "duplicado_rastreador": 0, "duplicado_vigencia": 0, "autoridad_ya_no_vigente": 0}
    cola.sort(key=lambda c: c.get("creado_en") or "", reverse=True)                # el más nuevo primero
    vistos_url, vistos_aut = set(), set()
    for c in cola:
        url = (c.get("url_fuente") or "").split("#")[0].rstrip("/")
        if c["agente"] == "rastreador":
            if url in indices:
                retirar(c, "otro", "Portada de un índice: el rastreador ahora busca los documentos de adentro y propone solo los relevantes.", prueba)
                n["portada_indice"] += 1
            elif url in vistos_url:
                retirar(c, "duplicado", "Misma página que otro ítem más reciente del rastreador.", prueba)
                n["duplicado_rastreador"] += 1
            vistos_url.add(url)
        elif c["agente"] == "control_vigencia" and c["titulo"].startswith("Dato con más de un año"):
            retirar(c, "duplicado", "Aviso individual reemplazado por un aviso agrupado por tipo de dato.", prueba)
            n["vencido_individual"] = n.get("vencido_individual", 0) + 1
        elif c["agente"] == "control_vigencia" and (c.get("propuesta") or {}).get("accion") == "marcar_no_vigente":
            aid = ((c.get("propuesta") or {}).get("parametros") or {}).get("autoridad_id")
            if aid and aid not in vigentes:
                retirar(c, "desactualizado", "La autoridad ya figura como no vigente (nómina actualizada con fuente).", prueba)
                n["autoridad_ya_no_vigente"] += 1
            elif aid in vistos_aut:
                retirar(c, "duplicado", "Aviso repetido sobre la misma autoridad: queda el más reciente.", prueba)
                n["duplicado_vigencia"] += 1
            vistos_aut.add(aid)
    if "--reiniciar-indices" in sys.argv:
        # Las propuestas de la búsqueda dirigida hechas con el filtro anterior se retiran y los índices se releen.
        for c in cola:
            if c["agente"] == "rastreador" and (c.get("propuesta") or {}).get("indice") and c["estado"] == "pendiente":
                retirar(c, "otro", "Falso positivo del filtro anterior (contaba palabras del menú del sitio): se reevalúa con el filtro corregido.", prueba)
                n["reevaluar"] = n.get("reevaluar", 0) + 1
        ids = [f["id"] for f in o.db().table("fuentes_monitoreadas").select("id,tipo").execute().data or [] if f["tipo"] in o.TIPOS_INDICE]
        borradas = 0
        for fid in ids:
            if prueba:
                borradas += len(o.db().table("fuente_urls_vistas").select("url").eq("fuente_id", fid).execute().data or [])
            else:
                borradas += len(o.db().table("fuente_urls_vistas").delete().eq("fuente_id", fid).execute().data or [])
        print(f"{'(prueba) ' if prueba else ''}índices reiniciados: {len(ids)} · URLs que se vuelven a leer: {borradas}")
    print(("(prueba) " if prueba else "") + f"retirados: {n} · pendientes antes: {len(cola)} · quedan: {len(cola) - sum(n.values())}")


if __name__ == "__main__":
    main()
