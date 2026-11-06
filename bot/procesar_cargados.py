"""Procesa los documentos (PDF, Word, planillas, imágenes) que el equipo cargó a mano en el panel (sitios que rechazan consultas desde servidores).

Para cada documento pendiente: lo baja del depósito privado, verifica la huella SHA-256, lo lee página por página
(OCR si es un escaneo), sube capturas de las páginas con hallazgos al depósito privado 'capturas' y lo propone
a la cola de revisión con el ENLACE ORIGINAL del sitio oficial. Nada se publica sin una persona.
Uso: python procesar_cargados.py
"""
import hashlib
import json

import orquestador_bots_audita as o
import analista_pdf as a


def principal():
    cli = o.db()
    pend = cli.table("documentos_cargados").select("*").eq("estado", "pendiente").execute().data or []
    insts = {i["slug"]: i for i in cli.table("instituciones").select("id,slug,nombre").execute().data or []}
    alias_juris, _, club_por_slug = o.contexto_jurisdicciones()
    print(f"documentos pendientes: {len(pend)}")
    import time
    fin = time.monotonic() + 100 * 60          # lo que no entra en 100 minutos se analiza en la corrida siguiente
    for d in sorted(pend, key=lambda x: x.get("creado_en") or ""):
        if time.monotonic() > fin:
            print("tiempo agotado: el resto queda para la próxima corrida"); break
        try:
            datos = cli.bajar_archivo("documentos-cargados", d["ruta"])
            sha = hashlib.sha256(datos).hexdigest()
            if sha != d["sha256"]:
                raise ValueError("la huella del archivo no coincide con la registrada")
            import convertir
            formato = d.get("formato") or convertir.formato_de(d["ruta"], datos)
            pdf = convertir.a_pdf(datos, formato)          # Word, planillas e imágenes se leen como PDF
            res = a.analizar(pdf, d["url_original"], sha)
            import vigia
            vigia.registrar_estructura(cli, d["juris_slug"], d["url_original"], res["por_pagina"])
            import rafam            # reportes de ejecución presupuestaria: se leen columna por columna y se controlan
            ejec = rafam.registrar(cli, d["juris_slug"], d["url_original"], sha, d["titulo"], pdf)
            marcas = o.relevancia(res["texto"], alias_juris.get(d["juris_slug"], {}))
            relevante = bool(marcas) or a.es_relevante(res["hallazgos"])
            resultado = {"ejecucion_rafam": {k: ejec.get(k) for k in ("tipo", "clasificacion", "desde", "hasta", "lineas")} if ejec else None,
                         "formato": formato, "paginas": res["paginas"], "paginas_ocr": res["paginas_ocr"],
                         "hallazgos": a.resumen_hallazgos(res["hallazgos"]), "temas": a.temas_de(res["hallazgos"])}
            if relevante:
                caps = a.subir_capturas(cli, sha, res["capturas"])
                cap = o.Captura(d["url_original"], 200, contenido=pdf, sha256=sha)
                ind, requiere, motivo = o.analizar_contenido(cap)
                ind.update({"caracteres": len(res["texto"]), "expedientes": o.extraer_expedientes(res["texto"]),
                            "cuits_entidades": o.extraer_cuits_entidades(res["texto"])})
                club = club_por_slug.get(d.get("club_slug") or "") or \
                    next((club_por_slug[m.split(":", 1)[1]] for m in marcas if m.startswith("menciona_club:")), None)
                inst = insts.get(d["juris_slug"]) or {}
                prop = {"portal_origen": "boletin_municipal" if d["juris_slug"].startswith("muni-") else "sitio_oficial",
                        "cargado_a_mano": True, "documento_cargado_id": d["id"], "indicadores": ind,
                        "coincidencias": marcas, "temas": resultado["temas"], "hallazgos": resultado["hallazgos"],
                        "capturas": caps, "paginas": res["paginas"], "paginas_ocr": res["paginas_ocr"],
                        "requiere_ocr_o_revision_humana": len(res["texto"]) < 200, "motivo_revision": None}
                r = o.proponer("analista_pdf", "documento_nuevo", f"{inst.get('nombre', d['juris_slug'])}: {d['titulo']}", cap,
                               club["id"] if club else None, None if club else inst.get("id"), prop,
                               texto_para_filtro=res["texto"][:20000])
                resultado["cola"] = r
            cli.table("documentos_cargados").update({"estado": "procesado", "resultado": resultado}).eq("id", d["id"]).execute()
            print(f"  {d['titulo'][:60]}: páginas={res['paginas']} ocr={res['paginas_ocr']} temas={resultado['temas']} "
                  f"→ {resultado.get('cola', 'sin hallazgos relevantes')}", flush=True)
        except Exception as e:
            cli.table("documentos_cargados").update({"estado": "error", "resultado": {"error": str(e)[:300]}}).eq("id", d["id"]).execute()
            print(f"  {d.get('titulo', '')[:60]}: error ({type(e).__name__}: {str(e)[:150]})", flush=True)


if __name__ == "__main__":
    principal()
