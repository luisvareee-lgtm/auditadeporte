"""Vigía: reglas objetivas sobre lo que los agentes leyeron. Cada alerta dice QUÉ encontró, POR QUÉ lo marca (regla y
norma), QUÉ PODRÍA EXPLICARLO sin irregularidad y QUÉ HACER. Las alertas son privadas: las ve el administrador en el
panel y nunca se publican solas. Una alerta no es una acusación: es una pregunta para verificar.

Reglas:
  huecos_numeracion   faltan números de decreto/resolución en lo que el municipio publicó de un año
  fraccionamiento     varias adjudicaciones al mismo proveedor en poco tiempo, cada una debajo de un tope legal y
                      que juntas lo superan
  mismo_expediente    (por venir) mismo expediente con montos distintos

Uso: python vigia.py            -> evalúa y guarda alertas; termina con código 3 si hay alertas NUEVAS (GitHub avisa)
"""
import json
import os
import sys
from datetime import date

AQUI = os.path.dirname(os.path.abspath(__file__))
UMBRALES = json.load(open(os.path.join(AQUI, "umbrales_compras.json"), encoding="utf-8"))

MIN_VISTAS_PARA_HUECOS = 15      # con pocos números vistos no se sabe si falta algo o si no se leyó
MIN_HUECO = 3                    # un número suelto que falta puede ser una anulación: se marca desde 3 seguidos
VENTANA_DIAS = 60


def rangos(faltan: list) -> list:
    out = []
    for n in faltan:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def regla_huecos(normas: list) -> list:
    """normas: [{juris_slug, tipo, numero, anio, url}]"""
    grupos = {}
    for n in normas:
        grupos.setdefault((n["juris_slug"], n["tipo"], n["anio"]), []).append(n)
    alertas = []
    for (juris, tipo, anio), ns in grupos.items():
        nums = sorted({n["numero"] for n in ns})
        if len(nums) < MIN_VISTAS_PARA_HUECOS:
            continue
        faltan = sorted(set(range(nums[0], nums[-1] + 1)) - set(nums))
        bloques = [r for r in rangos(faltan) if r[1] - r[0] + 1 >= MIN_HUECO]
        if not bloques:
            continue
        total = sum(r[1] - r[0] + 1 for r in bloques)
        txt = ", ".join(f"{a}" if a == b else f"{a} a {b}" for a, b in bloques[:12]) + ("…" if len(bloques) > 12 else "")
        plural = {"decreto": "decretos", "resolucion": "resoluciones", "ordenanza": "ordenanzas"}[tipo]
        alertas.append({
            "regla": "huecos_numeracion", "juris_slug": juris, "gravedad": "alta" if total >= 50 else "media",
            "clave": f"huecos:{juris}:{tipo}:{anio}:{nums[0]}-{nums[-1]}:{total}",
            "titulo": f"{total} {plural} de {anio} sin publicar entre el {nums[0]} y el {nums[-1]}",
            "explicacion": {
                "que": f"Leímos {len(nums)} {plural} de {anio} publicados, del {nums[0]} al {nums[-1]}. No encontramos estos números: {txt}.",
                "por_que": "La numeración de las normas es correlativa. Un salto de varios números seguidos indica normas que existen "
                           "pero no están en lo que leímos del boletín.",
                "norma": "En la Provincia de Buenos Aires, la Ley 14.491 (que modifica la Ley Orgánica de las Municipalidades) regula la "
                         "publicación de las normas municipales en el Boletín Oficial Municipal.",
                "puede_explicarse": "Puede que esos números sean de alcance particular (por ejemplo, de personal) y la norma no exija "
                                    "publicarlos; que estén en otra edición del boletín que todavía no leímos; o que se hayan anulado.",
                "que_hacer": "1) Revisá si hay ediciones del boletín que falten cargar. 2) Si no, pedí por acceso a la información "
                             "el listado de esos números con su objeto (sin datos personales). Los que traten de deporte, "
                             "subsidios o compras son los que importan."},
            "evidencia": [{"url": u} for u in sorted({n["url"] for n in ns})[:8]]})
    return alertas


def regla_fraccionamiento(adjs: list, umbrales: dict = UMBRALES) -> list:
    """adjs: [{juris_slug, proveedor, proveedor_n, monto, fecha, modalidad, url, pagina, extracto}]"""
    tope_directa = umbrales["provincia_buenos_aires"]["compra_directa_hasta"]
    tope_concurso = umbrales["provincia_buenos_aires"]["concurso_de_precios_hasta"]
    fuente = umbrales["provincia_buenos_aires"]["fuente"]
    alertas = []
    grupos = {}
    for a in adjs:
        if not a.get("fecha") or (a.get("modalidad") or "").startswith("licitacion"):
            continue
        grupos.setdefault((a["juris_slug"], a["proveedor_n"]), []).append(a)
    for (juris, prov), xs in grupos.items():
        if not juris.startswith("muni-"):
            continue
        xs.sort(key=lambda a: a["fecha"])
        for tope, nombre in ((tope_directa, "compra directa"), (tope_concurso, "concurso de precios")):
            debajo = [a for a in xs if a["monto"] <= tope]
            for i in range(len(debajo)):
                ini = date.fromisoformat(debajo[i]["fecha"])
                ventana = [a for a in debajo[i:] if (date.fromisoformat(a["fecha"]) - ini).days <= VENTANA_DIAS]
                suma = sum(a["monto"] for a in ventana)
                if len(ventana) >= 2 and suma > tope:
                    pesos = lambda v: "$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    alertas.append({
                        "regla": "fraccionamiento", "juris_slug": juris, "gravedad": "alta" if len(ventana) >= 3 else "media",
                        "clave": f"fracc:{juris}:{prov}:{nombre}:{ventana[0]['fecha']}:{len(ventana)}",
                        "titulo": f"{len(ventana)} adjudicaciones a {ventana[0]['proveedor']} en {VENTANA_DIAS} días: juntas superan el tope de {nombre}",
                        "explicacion": {
                            "que": f"Entre el {ventana[0]['fecha']} y el {ventana[-1]['fecha']} hay {len(ventana)} adjudicaciones al mismo proveedor, "
                                   f"cada una por debajo de {pesos(tope)} (tope de {nombre}). Suman {pesos(suma)}.",
                            "por_que": "Si se compra lo mismo en partes para que cada parte quede debajo del tope, se evita el procedimiento "
                                       "que corresponde al total (más competencia y más control). Eso se llama fraccionamiento o desdoblamiento.",
                            "norma": f"Art. 151 de la Ley Orgánica de las Municipalidades (Decreto-Ley 6769/58): define la modalidad según el monto. "
                                     f"Topes vigentes: {fuente}.",
                            "puede_explicarse": "Pueden ser compras de cosas distintas, necesidades que no se podían prever juntas, una "
                                                "emergencia, o un proveedor único. El programa no sabe qué se compró en cada una: hay que leerlas.",
                            "que_hacer": "1) Abrí cada documento y fijate si el objeto es el mismo. 2) Si lo es, pedí los expedientes completos "
                                         "(pedido de cotizaciones, justificación de la modalidad, órdenes de compra)."},
                        "evidencia": [{"url": a["url"], "pagina": a.get("pagina"), "extracto": a.get("extracto"), "monto": a["monto"],
                                       "fecha": a["fecha"]} for a in ventana][:8]})
                    break          # una alerta por proveedor y tope alcanza
    return alertas


def evaluar(cli) -> list:
    normas = cli.table("normas_vistas").select("juris_slug,tipo,numero,anio,url").execute().data or []
    adjs = cli.table("adjudicaciones_vistas").select("juris_slug,proveedor,proveedor_n,monto,fecha,modalidad,url,pagina,extracto") \
        .execute().data or []
    for a in adjs:
        a["monto"] = float(a["monto"])
    return regla_huecos(normas) + regla_fraccionamiento(adjs)


def guardar(cli, alertas: list) -> int:
    claves = {a["clave"] for a in cli.table("alertas_vigia").select("clave").execute().data or []}
    nuevas = [a for a in alertas if a["clave"] not in claves]
    if nuevas:
        cli.table("alertas_vigia").insert(nuevas).execute()
    return len(nuevas)


def registrar_estructura(cli, juris: str, url: str, por_pagina: list):
    """Guarda números de normas y adjudicaciones que aparecen en un documento leído (relevante o no)."""
    import extractores as ex
    if not juris:
        return
    anio_doc = None
    filas_n, filas_a = [], []
    for i, t in enumerate(por_pagina, 1):
        for tipo, num, anio in ex.normas(t, anio_doc):
            anio_doc = anio
            filas_n.append({"juris_slug": juris, "tipo": tipo, "numero": num, "anio": anio, "url": url, "pagina": i})
        for a in ex.adjudicaciones(t):
            filas_a.append({"juris_slug": juris, **a, "url": url, "pagina": i})
    try:
        if filas_n:
            vistos = {(f["tipo"], f["numero"], f["anio"]) for f in filas_n}
            filas_n = [next(f for f in filas_n if (f["tipo"], f["numero"], f["anio"]) == k) for k in vistos]
            cli.table("normas_vistas").upsert(filas_n, on_conflict="juris_slug,tipo,numero,anio", ignore_duplicates=True).execute()
        if filas_a:
            cli.table("adjudicaciones_vistas").upsert(filas_a, on_conflict="juris_slug,proveedor_n,monto,url", ignore_duplicates=True).execute()
    except Exception as e:                # sin db/18 todavía: no frena al resto
        print(f"  vigía: no se pudo registrar estructura ({str(e)[:100]})", flush=True)


def main():
    import orquestador_bots_audita as o
    cli = o.db()
    try:
        alertas = evaluar(cli)
        n = guardar(cli, alertas)
    except Exception as e:           # sin db/18 o la base no responde: no es una alerta, no se pone en rojo
        print(f"vigía: no se pudo evaluar ({type(e).__name__}: {str(e)[:150]})")
        return
    print(f"alertas evaluadas: {len(alertas)} · nuevas: {n}")
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen and n:
        open(resumen, "a", encoding="utf-8").write(f"## Vigía: {n} alerta(s) nueva(s)\n\nEntrá al panel → pestaña Alertas. "
                                                    "El detalle no se muestra acá porque este registro es público.\n")
    if n:
        sys.exit(3)          # la corrida queda en rojo: GitHub le manda un correo al dueño del repositorio


if __name__ == "__main__":
    main()
