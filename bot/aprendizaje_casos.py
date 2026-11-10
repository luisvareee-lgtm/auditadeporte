"""Aprende de las decisiones del panel (aprobar / descartar) para ORDENAR la cola de revisión: lo más probable
primero. No descarta nada solo: decide siempre una persona.

Trabaja únicamente con la memoria léxica (db/29): por cada posteo, qué términos de un diccionario cerrado
aparecieron y con qué contexto. Nunca hay texto, nombres ni palabras fuera de esa lista.

1. Entrena: cuenta, para cada marca (término, señal, tipo de cuenta), en cuántos aprobados y descartados apareció
   (Bayes ingenuo con suavizado). Con pocas decisiones no puntúa: prefiere callar a adivinar.
2. Puntúa lo pendiente (0 a 100) y lo guarda para que el panel lo ordene.
3. --reevaluar: vuelve a aplicar las reglas de hoy a todo lo ya leído, sin consultar a Meta: saca de la cola lo
   que ya no pasa y agrega lo que ahora sí.
Uso: python aprendizaje_casos.py [--reevaluar] [--prueba]
"""
import json
import math
import sys

MIN_CASOS, MIN_POR_CLASE = 20, 5


def marcas(fila: dict) -> set:
    """Las marcas de una fila de memoria_lexica."""
    h = fila.get("huella") or {}
    m = {"t:" + t for t in fila.get("terminos") or []} | {"s:" + k for k in (h.get("s") or {})}
    m |= {"ctx:" + k + ":" + ("si" if ("f" in v or ("d" in v and "p" in v)) else "no") for k, v in (h.get("s") or {}).items()}
    if "c" in h:
        m.add("pide_plata")
    if fila.get("tipo_cuenta"):
        m.add("tipo:" + fila["tipo_cuenta"])
    if fila.get("cuenta"):
        m.add("cuenta:" + fila["cuenta"])
    return m


def entrenar(decididas: list) -> dict:
    """{"n": {"aprobado": N, "descartado": N}, "m": {marca: [veces en aprobados, veces en descartados]}}"""
    mod = {"n": {"aprobado": 0, "descartado": 0}, "m": {}}
    for f in decididas:
        d = f.get("decision")
        if d not in mod["n"]:
            continue
        mod["n"][d] += 1
        for x in marcas(f):
            mod["m"].setdefault(x, [0, 0])[0 if d == "aprobado" else 1] += 1
    return mod


def listo(mod: dict) -> bool:
    n = mod["n"]
    return n["aprobado"] + n["descartado"] >= MIN_CASOS and min(n.values()) >= MIN_POR_CLASE


def puntaje(fila: dict, mod: dict):
    """Probabilidad (0-100) de que una persona la apruebe, o None si todavía no hay casos suficientes."""
    if not listo(mod):
        return None
    na, nd = mod["n"]["aprobado"], mod["n"]["descartado"]
    logit = math.log(na / nd)
    for x in marcas(fila):
        a, d = mod["m"].get(x, (0, 0))
        if a + d < 2:                      # una marca vista una sola vez no dice nada
            continue
        logit += math.log(((a + 1) / (na + 2)) / ((d + 1) / (nd + 2)))
    logit = max(-12.0, min(12.0, logit))
    return round(100 / (1 + math.exp(-logit)))


def pesos(mod: dict, n=12) -> list:
    """Las marcas que más empujan hacia aprobar (+) o descartar (−), para poder leer qué aprendió."""
    na, nd = max(mod["n"]["aprobado"], 1), max(mod["n"]["descartado"], 1)
    w = [(round(math.log(((a + 1) / (na + 2)) / ((d + 1) / (nd + 2))), 2), k, a, d) for k, (a, d) in mod["m"].items()
         if a + d >= 3 and not k.startswith("cuenta:")]
    w.sort()
    return w[:n] + w[-n:]


def reevaluar(memoria: list, nombres: dict) -> dict:
    """Con las reglas de hoy: qué permalinks tienen que estar en la cola de publicaciones y cuáles son colectas.
    Devuelve {"senales": {permalink: fila para publicaciones_relevantes}, "colectas": {permalinks}}."""
    import relevar_colectas as rc
    out = {"senales": {}, "colectas": set()}
    for f in memoria:
        if f.get("decision"):
            continue
        h = f.get("huella") or {}
        h = {"s": h.get("s") or {}, **({"c": h["c"]} if "c" in h else {})}
        propia = rc.contexto_de(f["cuenta"], nombres.get(f["cuenta"], "")) is None
        if rc.es_colecta_de(h, propia):
            out["colectas"].add(f["permalink"])
            continue
        sn = rc.senales_de(h, propia)
        if f.get("tipo_cuenta") == "institucion":
            sn = [x for x in sn if x != "apoyo_empresas"]
        if sn:
            out["senales"][f["permalink"]] = {"cuenta": f["cuenta"], "nombre_cuenta": nombres.get(f["cuenta"], f["cuenta"]),
                                              "tipo_cuenta": f.get("tipo_cuenta") or "club", "fecha": f["fecha"], "permalink": f["permalink"],
                                              "senales": sn, "torneos": (f.get("huella") or {}).get("tor") or []}
    return out


def _todas(cli, tabla, cols, filtro=None):
    out, desde = [], 0
    while True:
        q = cli.table(tabla).select(cols).order("permalink").range(desde, desde + 999)
        r = (filtro(q) if filtro else q).execute().data or []
        out += r
        if len(r) < 1000:
            return out
        desde += 1000


def main():
    import orquestador_bots_audita as o
    prueba = "--prueba" in sys.argv
    cli = o.db()
    try:
        memoria = _todas(cli, "memoria_lexica", "permalink,cuenta,tipo_cuenta,fecha,terminos,huella,decision")
    except Exception as e:
        print("Falta correr db/29 (memoria_lexica):", str(e)[:100]); return
    mod = entrenar(memoria)
    print("DECISIONES:", json.dumps(mod["n"]), "| huellas guardadas:", len(memoria), "| puntúa:", "sí" if listo(mod) else f"todavía no (hacen falta {MIN_CASOS} decisiones y {MIN_POR_CLASE} de cada tipo)")
    if listo(mod):
        print("LO QUE APRENDIÓ (peso, marca, aprobadas, descartadas):")
        for w in pesos(mod):
            print("  ", *w)
    por_link = {f["permalink"]: f for f in memoria}
    if "--reevaluar" in sys.argv:
        try:
            import actualidad_redes as ar
            nombres = {d["instagram"].lower(): d["nombre"] for d in ar.cuentas_a_leer() if d.get("instagram")}
        except Exception:
            nombres = {}
        r = reevaluar(memoria, nombres)
        pend = _todas(cli, "publicaciones_relevantes", "id,permalink", lambda q: q.eq("revisada", False))
        fuera = [p for p in pend if p["permalink"] in por_link and p["permalink"] not in r["senales"]]
        ya = {p["permalink"] for p in _todas(cli, "publicaciones_relevantes", "permalink")}
        nuevas = [f for k, f in r["senales"].items() if k not in ya]
        pendc = _todas(cli, "colectas_relevadas", "id,permalink", lambda q: q.eq("revisada", False))
        fuerac = [p for p in pendc if p["permalink"] in por_link and p["permalink"] not in r["colectas"]]
        print("REEVALUAR:", json.dumps({"salen_de_la_cola": len(fuera), "entran": len(nuevas), "colectas_que_ya_no_pasan": len(fuerac)}))
        if not prueba:
            for p in fuera:
                cli.table("publicaciones_relevantes").delete().eq("id", p["id"]).eq("revisada", False).execute()
            for p in fuerac:
                cli.table("colectas_relevadas").delete().eq("id", p["id"]).eq("revisada", False).execute()
            if nuevas:
                cli.table("publicaciones_relevantes").upsert(nuevas, on_conflict="permalink", ignore_duplicates=True).execute()
    if not listo(mod) or prueba:
        return
    n = 0
    for tabla in ("publicaciones_relevantes", "colectas_relevadas"):
        try:
            for p in _todas(cli, tabla, "id,permalink,puntaje", lambda q: q.eq("revisada", False)):
                f = por_link.get(p["permalink"])
                pt = puntaje(f, mod) if f else None
                if pt is not None and pt != p.get("puntaje"):
                    cli.table(tabla).update({"puntaje": pt}).eq("id", p["id"]).execute()
                    n += 1
        except Exception as e:
            print(f"no se pudo puntuar {tabla}:", str(e)[:100])
    print("puntajes actualizados:", n)


if __name__ == "__main__":
    main()
