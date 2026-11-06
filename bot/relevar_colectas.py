"""AuditaDeporte - Relevamiento de colectas en Instagram (API oficial de Meta, Business Discovery).

Lee varios años de posteos de las cuentas OFICIALES (clubes, instituciones y selecciones) y busca convocatorias a
colectas, rifas o pedidos de fondos. De cada una guarda solo datos objetivos:
  fecha, enlace al posteo, para qué era (viaje, inscripción, silla/equipamiento, indumentaria, general),
  qué torneo menciona y qué montos declara la propia cuenta.

Privacidad: NO guarda el texto del posteo, ni nombres, ni alias o CBU, ni titulares de cuentas. Se descartan los
posteos que hablan de salud o tratamientos de una persona. No se leen cuentas personales de deportistas.
Un posteo de colecta es una convocatoria pública de la propia cuenta: no prueba nada sobre nadie.

Secrets: META_TOKEN, IG_USER_ID, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
Uso: python relevar_colectas.py [--desde 2024-01-01] [--prueba]   (--prueba: no escribe en la base)
     python relevar_colectas.py --publicar   (arma datos/colectas.json con los agregados, sin enlaces de terceros)
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone

import orquestador_bots_audita as o

AGENTE = "relevar_colectas"
SELECCIONES = {"laslobasbasquet": "Selección argentina femenina (Las Lobas)"}   # cuentas oficiales de equipos nacionales
PAGINAS_MAX = 12                      # 12 x 50 posteos por cuenta como máximo
AQUI = os.path.dirname(os.path.abspath(__file__))

RE_COLECTA = re.compile(r"\b(rifas?|bono contribucion|colectas?|alias|cbu|cvu|ayudanos|ayudenos|donacion(es)?|dona(r|nos)?|"
                        r"aporte solidario|campana solidaria|vaquita|mercado pago|necesitamos (juntar|recaudar)|recaudar)\b")
RE_SALUD = re.compile(r"\b(operacion|cirugia|tratamiento|internad[oa]|medicamentos?|rehabilitacion|protesis|enfermedad)\b")
FINALIDADES = {
    "viaje_torneo": r"\b(viajes?|viajar|pasajes?|traslados?|micros?|alojamiento|hotel|estadia|vuelos?)\b",
    "inscripcion": r"\b(inscripcion|fichajes?|aranceles?)\b",
    "silla_equipamiento": r"\b(sillas?|cubiertas?|repuestos?|ruedas|equipamiento|rayos|ejes?|rulemanes)\b",
    "indumentaria": r"\b(camisetas?|indumentaria|camperas?|conjuntos?|equipo de juego)\b",
}
TORNEOS = {
    "mundial": r"\bmundial(es)?\b", "repechaje": r"\brepechaje\b", "copa_america": r"\bcopa america\b",
    "parapanamericanos": r"\bparapanamericanos?\b", "paralimpicos": r"\bparalimpic\w*\b", "sudamericano": r"\bsudamerican\w*\b",
    "liga_nacional": r"\b(liga nacional|torneo nacional|nacional de clubes|final four|cuadrangular|liga argentina)\b",
    "juegos_bonaerenses": r"\bjuegos bonaerenses\b",
}
RE_MONTO = re.compile(r"(?i)(u\$s|us\$|usd|dolares|\$)\s?(\d{1,3}(?:[.\s]\d{3})+|\d{4,})(?:,\d{1,2})?(?:\s?(mil|millones?))?")


def _monto(m):
    mon = "USD" if m.group(1).lower() in ("u$s", "us$", "usd", "dolares") else "ARS"
    v = float(re.sub(r"[.\s]", "", m.group(2)))
    mult = (m.group(3) or "").lower()
    v *= 1_000_000 if mult.startswith("millon") else 1000 if mult == "mil" else 1
    return {"moneda": mon, "valor": v}


def clasificar(caption: str):
    """None si no es una colecta (o si habla de la salud de una persona). Si lo es: finalidades, torneos y montos."""
    t = o._norm(caption or "")
    if not RE_COLECTA.search(t) or RE_SALUD.search(t):
        return None
    fin = [k for k, rx in FINALIDADES.items() if re.search(rx, t)] or ["general"]
    tor = [k for k, rx in TORNEOS.items() if re.search(rx, t)]
    montos = []
    for m in RE_MONTO.finditer(caption or ""):
        x = _monto(m)
        if x["valor"] >= 1000 and x not in montos:
            montos.append(x)
    return {"finalidades": fin, "torneos": tor, "montos": montos[:4]}


def leer_historial(usuario: str, propia: str, desde: date):
    """Posteos desde una fecha, paginando. Devuelve [{timestamp, permalink, caption}] (en memoria)."""
    import actualidad_redes as ar
    ig, out, after = os.environ["IG_USER_ID"], [], None
    campos = "timestamp,permalink,caption"
    for _ in range(PAGINAS_MAX):
        pag = f".after({after})" if after else ""
        if usuario.lower() == (propia or "").lower():
            d = ar.graph(ig, f"media{pag}.limit(50){{{campos}}}").get("media") or {}
        else:
            d = (ar.graph(ig, f"business_discovery.username({usuario}){{media{pag}.limit(50){{{campos}}}}}")
                 .get("business_discovery") or {}).get("media") or {}
        posts = d.get("data") or []
        out += posts
        after = ((d.get("paging") or {}).get("cursors") or {}).get("after")
        if not posts or not after or any(ar._fecha(p["timestamp"]) < desde for p in posts if p.get("timestamp")):
            break
        time.sleep(ar.PAUSA)
    return [p for p in out if p.get("timestamp") and ar._fecha(p["timestamp"]) >= desde]


def relevar_cuenta(usuario, nombre, tipo, posts):
    filas = []
    for p in posts:
        c = clasificar(p.get("caption"))
        if not c or not p.get("permalink"):
            continue
        filas.append({"cuenta": usuario.lower(), "nombre_cuenta": nombre, "tipo_cuenta": tipo, "fecha": p["timestamp"][:10],
                      "permalink": p["permalink"], **c})
    return filas


def agregar(filas: list) -> dict:
    por_anio, por_fin, por_torneo, por_cuenta, montos = {}, {}, {}, {}, {}
    for f in filas:
        a = f["fecha"][:4]
        por_anio[a] = por_anio.get(a, 0) + 1
        for x in f["finalidades"]:
            por_fin[x] = por_fin.get(x, 0) + 1
        for x in f["torneos"]:
            por_torneo[x] = por_torneo.get(x, 0) + 1
        k = f["nombre_cuenta"]
        c = por_cuenta.setdefault(k, {"cuenta": f["cuenta"], "tipo": f["tipo_cuenta"], "colectas": 0, "ultima": None, "finalidades": {}})
        c["colectas"] += 1
        c["ultima"] = max(c["ultima"] or f["fecha"], f["fecha"])
        for x in f["finalidades"]:
            c["finalidades"][x] = c["finalidades"].get(x, 0) + 1
        for m in f["montos"]:
            montos.setdefault(m["moneda"], []).append(m["valor"])
    return {"total": len(filas), "por_anio": dict(sorted(por_anio.items())), "por_finalidad": por_fin, "por_torneo": por_torneo,
            "por_cuenta": dict(sorted(por_cuenta.items(), key=lambda kv: -kv[1]["colectas"])),
            "montos_declarados": {k: {"cantidad": len(v), "mayor": max(v)} for k, v in montos.items()}}


def cuentas():
    import actualidad_redes as ar
    out = [(d["instagram"], d["nombre"], "club" if d["tipo"] == "club" else "institucion") for d in ar.cuentas_a_leer()]
    out += [(u, n, "seleccion") for u, n in SELECCIONES.items()]
    vistos, res = set(), []
    for u, n, t in out:
        if u.lower() not in vistos:
            vistos.add(u.lower()); res.append((u, n, t))
    return res


def publicar(cli=None):
    """datos/colectas.json: solo agregados y enlaces a posteos de cuentas oficiales."""
    cli = cli or o.db()
    filas = cli.table("colectas_relevadas").select("cuenta,nombre_cuenta,tipo_cuenta,fecha,permalink,finalidades,torneos,montos") \
        .execute().data or []
    datos = {"actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%d"), **agregar(filas),
             "recientes": [{k: f[k] for k in ("nombre_cuenta", "tipo_cuenta", "fecha", "permalink", "finalidades", "torneos")}
                           for f in sorted(filas, key=lambda x: x["fecha"], reverse=True)[:30]]}
    ruta = os.path.join(AQUI, "..", "datos", "colectas.json")
    nuevo = json.dumps(datos, ensure_ascii=False, indent=1)
    viejo = open(ruta, encoding="utf-8").read() if os.path.exists(ruta) else ""
    sin_fecha = lambda t: "\n".join(l for l in t.splitlines() if '"actualizado"' not in l)
    if sin_fecha(nuevo) != sin_fecha(viejo):
        open(ruta, "w", encoding="utf-8").write(nuevo + "\n")
    print("colectas publicadas:", datos["total"])


def main():
    if "--publicar" in sys.argv:
        try:
            return publicar()
        except Exception as e:
            print("sin tabla colectas_relevadas todavía (db/21):", str(e)[:120]); return
    import actualidad_redes as ar
    desde = date.fromisoformat(sys.argv[sys.argv.index("--desde") + 1]) if "--desde" in sys.argv else date(2024, 1, 1)
    prueba = "--prueba" in sys.argv
    propia = ar.graph(os.environ["IG_USER_ID"], "username").get("username")
    todas, estados = [], {}
    for usuario, nombre, tipo in cuentas():
        try:
            posts = leer_historial(usuario, propia, desde)
            filas = relevar_cuenta(usuario, nombre, tipo, posts)
            del posts                                  # los textos no se conservan
            todas += filas
            estados[usuario] = f"ok ({len(filas)} colectas)"
        except ar.ErrorMeta as e:
            estados[usuario] = e.estado
        time.sleep(ar.PAUSA)
    print("CUENTAS:", json.dumps(estados, ensure_ascii=False))
    print("AGREGADO:", json.dumps(agregar(todas), ensure_ascii=False))
    if prueba or not todas:
        return
    try:
        o.db().table("colectas_relevadas").upsert(todas, on_conflict="permalink").execute()
        print("guardadas:", len(todas))
    except Exception as e:
        print("no se pudo guardar (¿falta db/21?):", str(e)[:150])


if __name__ == "__main__":
    main()
