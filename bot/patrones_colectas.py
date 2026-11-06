"""Patrones de colectas: agrupa las colectas parecidas para ver qué problema se repite.

Cada colecta se describe con rasgos objetivos: para qué (finalidad), cómo se pide (rifa, venta, alias, evento…),
a quién (personas, empresas, Estado), para qué torneo y en qué mes. Dos colectas se parecen si comparten
la mayoría de esos rasgos (índice de Jaccard). Para cada grupo se informa cuántas hubo, en cuántas cuentas,
en qué meses, con qué montos, con cuánta anticipación y qué tan cubrible es con patrocinio (RSE).
No usa textos ni datos personales: solo los rasgos que guardó el relevamiento.
"""
from datetime import date

UMBRAL = 0.5
# qué tan resoluble es cada necesidad con patrocinio: bien o servicio concreto, con proveedor y visible
RSE = {"silla_equipamiento": "alta", "indumentaria": "alta", "viaje_torneo": "alta", "inscripcion": "media", "general": "baja"}
NOMBRE = {"viaje_torneo": "viajes a torneos", "inscripcion": "inscripciones", "silla_equipamiento": "sillas y equipamiento",
          "indumentaria": "indumentaria", "general": "gastos generales"}
POR_QUE = {
    "alta": "Es un bien o servicio concreto: una empresa puede pagar directo al proveedor y mostrar su marca.",
    "media": "Se paga a un organizador (federación internacional, liga): patrocinable, pero primero corresponde pedirlo al Estado o a la federación.",
    "baja": "Es un gasto general sin destino claro: difícil de patrocinar; conviene detallarlo en necesidades concretas.",
}


def rasgos(c: dict) -> set:
    mes = (c.get("fecha") or "")[5:7]
    return ({f"fin:{x}" for x in c.get("finalidades") or []} | {f"tipo:{x}" for x in c.get("tipos_pedido") or []} |
            {f"tor:{x}" for x in c.get("torneos") or []} | ({f"mes:{mes}"} if mes else set()))


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def agrupar(colectas: list, umbral: float = UMBRAL) -> list:
    """Agrupamiento simple y explicable: cada colecta entra al grupo más parecido si supera el umbral."""
    grupos = []
    for c in sorted(colectas, key=lambda x: x.get("fecha") or ""):
        r = rasgos(c)
        mejor, sim = None, 0.0
        for g in grupos:
            s = jaccard(r, g["centro"])
            if s > sim:
                mejor, sim = g, s
        if mejor and sim >= umbral:
            mejor["miembros"].append(c)
            # el centro son los rasgos que tiene al menos la mitad del grupo
            cuenta = {}
            for m in mejor["miembros"]:
                for x in rasgos(m):
                    cuenta[x] = cuenta.get(x, 0) + 1
            mejor["centro"] = {x for x, n in cuenta.items() if n * 2 >= len(mejor["miembros"])} or r
        else:
            grupos.append({"centro": r, "miembros": [c]})
    return grupos


def _dias_anticipacion(c):
    try:
        return (date.fromisoformat(c["fecha_limite"]) - date.fromisoformat(c["fecha"][:10])).days if c.get("fecha_limite") else None
    except ValueError:
        return None


def patrones(colectas: list) -> list:
    out = []
    for g in agrupar(colectas):
        ms = g["miembros"]
        fines = {}
        for m in ms:
            for x in m.get("finalidades") or ["general"]:
                fines[x] = fines.get(x, 0) + 1
        principal = max(fines, key=fines.get)
        cuenta = lambda clave: sorted({x for m in ms for x in m.get(clave) or []})
        montos = {}
        for m in ms:
            for x in m.get("montos") or []:
                montos.setdefault(x["moneda"], []).append(x["valor"])
        meses = {}
        for m in ms:
            if m.get("fecha"):
                meses[m["fecha"][5:7]] = meses.get(m["fecha"][5:7], 0) + 1
        anticip = [d for d in (_dias_anticipacion(m) for m in ms) if d is not None]
        nivel = RSE.get(principal, "baja")
        out.append({
            "necesidad": NOMBRE.get(principal, principal), "finalidad": principal, "colectas": len(ms),
            "cuentas": len({m.get("cuenta") for m in ms}), "tipos_pedido": cuenta("tipos_pedido"), "torneos": cuenta("torneos"),
            "destinatarios": cuenta("destinatarios"), "meses": dict(sorted(meses.items())),
            "montos": {k: {"menor": min(v), "mayor": max(v)} for k, v in montos.items()},
            "dias_de_anticipacion": round(sum(anticip) / len(anticip)) if anticip else None,
            "rse": nivel, "por_que_rse": POR_QUE[nivel],
            "desde": min(m["fecha"] for m in ms), "hasta": max(m["fecha"] for m in ms)})
    out.sort(key=lambda p: (-p["colectas"], -p["cuentas"]))
    return out


def resumen_texto(ps: list) -> str:
    if not ps:
        return "Todavía no hay colectas relevadas."
    lineas = []
    for i, p in enumerate(ps[:8], 1):
        lineas.append(f"{i}. {p['necesidad'].capitalize()}: {p['colectas']} colecta(s) en {p['cuentas']} cuenta(s), "
                      f"de {p['desde']} a {p['hasta']}. Cómo se pidió: {', '.join(p['tipos_pedido']) or '—'}. "
                      f"Torneos: {', '.join(p['torneos']) or '—'}. Patrocinio: {p['rse']}.")
    return "\n".join(lineas)
