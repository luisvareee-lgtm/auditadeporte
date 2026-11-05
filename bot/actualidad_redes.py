"""AuditaDeporte - Actualidad en Instagram (API oficial de Meta, Business Discovery).

Por cada cuenta de Instagram cargada en clubes / instituciones (y la propia cuenta que funciona de llave):
  * guarda una foto del día en redes_actividad: seguidores, publicaciones, fecha del último posteo,
    posteos en los últimos 90 días, y si la cuenta se pudo leer;
  * si los posteos del último año nombran una división ("Primera División", "2da división", ...),
    propone actualizar la división del club, con los enlaces a los posteos como evidencia;
  * si un posteo de los últimos 90 días menciona colecta / viaje / equipamiento / convenio / balance,
    lo propone como novedad (con un resumen neutro, SIN copiar el texto del posteo).

NO guarda textos de posteos, fotos, comentarios ni nombres de personas: hay menores en los planteles.
Los textos se leen en memoria solo para buscar palabras clave y se descartan.
Todo lo que cambia algo pasa por la cola de revisión: una persona aprueba desde el panel.

Secrets: META_TOKEN (token de página), IG_USER_ID (id de la cuenta llave), SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
Uso: python actualidad_redes.py [--prueba]     (--prueba: lee la cuenta llave y FABA, imprime, no escribe)
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import orquestador_bots_audita as o

AGENTE = "actualidad_redes"
DIAS_INACTIVA = 180             # sin publicar hace más de esto: aviso para confirmar si el club sigue compitiendo
GRAPH = "https://graph.facebook.com/v27.0"
PAUSA = 2                                   # segundos entre consultas (límite de Meta: 200 por hora)
CAMPOS = "username,name,followers_count,media_count,media.limit(50){timestamp,permalink,caption,media_type}"
CUENTAS_INSTITUCIONES = {"faba": "basquetadaptadofaba"}   # si la institución no tiene instagram cargado

DIVISIONES = {
    "1ra": r"\b(?:primera|1\s?(?:ra|era|°|º))\s+(?:division|div)\b",
    "2da": r"\b(?:segunda|2\s?(?:da|°|º))\s+(?:division|div)\b",
    "3ra": r"\b(?:tercera|3\s?(?:ra|era|°|º))\s+(?:division|div)\b",
    "desarrollo": r"\b(?:division|liga|torneo|categoria)\s+(?:de\s+)?desarrollo\b",
}
MARCAS = {"colecta": r"\b(rifa|sorteo|bono contribucion|colecta|cbu|alias|ayudanos a viajar|vendemos|donacion)\b",
          "viaje": r"\b(viaje|traslado|pasajes?|gira)\b",
          "equipamiento": r"\b(silla|sillas|cubiertas?|repuestos?|equipamiento)\b",
          "convenio": r"\b(convenio|subsidio|beca|municipio|municipalidad|secretaria de deportes)\b",
          "balance": r"\b(balance|memoria|rendicion)\b"}


class ErrorMeta(Exception):
    def __init__(self, estado, mensaje):
        super().__init__(mensaje)
        self.estado = estado


def _sin_token(t: str) -> str:
    tok = os.environ.get("META_TOKEN", "")
    return t.replace(tok, "[token]") if tok else t


def graph(ruta: str, campos: str) -> dict:
    url = f"{GRAPH}/{ruta}?" + urllib.parse.urlencode({"fields": campos, "access_token": os.environ["META_TOKEN"]})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": o.UA}), timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except Exception:
            err = {}
        cod, msj = err.get("code"), _sin_token(err.get("message", f"http_{e.code}"))
        if cod == 190:
            raise ErrorMeta("token_vencido", msj)
        if cod in (4, 17, 32, 613):
            raise ErrorMeta("limite_meta", msj)
        if cod in (10, 200) or "permission" in msj.lower():
            raise ErrorMeta("sin_acceso", msj)
        if cod == 110 or err.get("error_subcode") == 2207013 or "cannot be found" in msj.lower():
            raise ErrorMeta("no_profesional_o_inexistente", msj)
        raise ErrorMeta("error", msj)
    except Exception as e:
        raise ErrorMeta("error", _sin_token(str(e)))


def leer_cuenta(usuario: str, propia: str):
    """La cuenta llave se lee directo; las demás, por Business Discovery."""
    ig = os.environ["IG_USER_ID"]
    if usuario.lower() == (propia or "").lower():
        return graph(ig, CAMPOS)
    d = graph(ig, f"business_discovery.username({usuario}){{{CAMPOS}}}")
    return d.get("business_discovery") or {}


def _fecha(ts: str) -> date:
    return datetime.strptime(ts[:10], "%Y-%m-%d").date()


def analizar(cuenta: dict, hoy: date = None) -> dict:
    """Resume la cuenta. Los textos de posteos se usan acá y no salen de esta función."""
    hoy = hoy or datetime.now(timezone.utc).date()
    posts = (cuenta.get("media") or {}).get("data") or []
    fechas = sorted((_fecha(p["timestamp"]) for p in posts if p.get("timestamp")), reverse=True)
    divisiones, novedades = {}, []
    for p in posts:
        if not p.get("timestamp") or not p.get("permalink"):
            continue
        f, txt = _fecha(p["timestamp"]), o._norm(p.get("caption") or "")
        if (hoy - f).days <= 365:
            for div, rx in DIVISIONES.items():
                if re.search(rx, txt):
                    d = divisiones.setdefault(div, {"menciones": 0, "ultima": None, "enlaces": []})
                    d["menciones"] += 1
                    d["ultima"] = max(d["ultima"] or f.isoformat(), f.isoformat())
                    if len(d["enlaces"]) < 5:
                        d["enlaces"].append(p["permalink"])
        if (hoy - f).days <= 90:
            marcas = [k for k, rx in MARCAS.items() if re.search(rx, txt)]
            if marcas:
                novedades.append({"permalink": p["permalink"], "fecha": f.isoformat(),
                                  "tipo": p.get("media_type"), "marcas": marcas})
    return {"usuario": cuenta.get("username"), "seguidores": cuenta.get("followers_count"),
            "publicaciones": cuenta.get("media_count"),
            "ultimo_posteo": fechas[0].isoformat() if fechas else None,
            "dias_sin_publicar": (hoy - fechas[0]).days if fechas else None,
            "posteos_90d": sum(1 for f in fechas if (hoy - f).days <= 90),
            "divisiones": divisiones, "novedades": novedades}


def division_probable(divisiones: dict):
    """La división más mencionada en el último año. Si hay empate, ninguna: lo decide una persona."""
    if not divisiones:
        return None
    orden = sorted(divisiones.items(), key=lambda kv: (kv[1]["menciones"], kv[1]["ultima"]), reverse=True)
    if len(orden) > 1 and orden[0][1]["menciones"] == orden[1][1]["menciones"]:
        return None
    return orden[0][0]


def cuentas_a_leer():
    clubes = o.db().table("clubes").select("id,slug,nombre,instagram,division,estado_afiliacion").execute().data or []
    insts = o.db().table("instituciones").select("id,slug,nombre,instagram").execute().data or []
    out = [{"tipo": "club", **c} for c in clubes if c.get("instagram")]
    for i in insts:
        u = i.get("instagram") or CUENTAS_INSTITUCIONES.get(i["slug"])
        if u:
            out.append({"tipo": "inst", **i, "instagram": u})
    return out


def _cap(url: str, datos: dict) -> o.Captura:
    cuerpo = json.dumps(datos, sort_keys=True, ensure_ascii=False).encode()
    return o.Captura(url, 200, cuerpo, hashlib.sha256(cuerpo).hexdigest())


def guardar_foto(dest: dict, res: dict, estado: str, detalle: str = None):
    fila = {"club_id": dest["id"] if dest["tipo"] == "club" else None,
            "institucion_id": dest["id"] if dest["tipo"] == "inst" else None,
            "plataforma": "instagram", "cuenta": dest["instagram"].lower(),
            "fecha_consulta": datetime.now(timezone.utc).date().isoformat(), "estado": estado,
            "seguidores": res.get("seguidores"), "publicaciones": res.get("publicaciones"),
            "ultimo_posteo": res.get("ultimo_posteo"), "posteos_90d": res.get("posteos_90d"),
            "detalle": {"divisiones": {k: {"menciones": v["menciones"], "ultima": v["ultima"]}
                                       for k, v in (res.get("divisiones") or {}).items()},
                        "mensaje": detalle}}
    o.db().table("redes_actividad").upsert(fila, on_conflict="cuenta,fecha_consulta").execute()


def proponer(dest: dict, res: dict) -> dict:
    cont = {"division": 0, "novedad": 0, "inactiva": 0}
    cid = dest["id"] if dest["tipo"] == "club" else None
    iid = dest["id"] if dest["tipo"] == "inst" else None
    u = dest["instagram"]
    div = division_probable(res["divisiones"]) if dest["tipo"] == "club" else None
    if div and (div != dest.get("division") or dest.get("estado_afiliacion") != "activo"):
        ev = res["divisiones"][div]
        r = o.proponer(AGENTE, "propuesta_cambio",
                       f"{dest['nombre']}: Instagram menciona {div} división ({ev['menciones']} posteos, último {ev['ultima']})",
                       _cap(ev["enlaces"][0], {"cuenta": u, "division": div, **ev}), club_id=cid,
                       propuesta={"accion": "actualizar_division_club", "fuente": "instagram_oficial",
                                  "parametros": {"division": div, "fuente_url": ev["enlaces"][0], "fecha": ev["ultima"]},
                                  "actual": {"division": dest.get("division"), "estado_afiliacion": dest.get("estado_afiliacion")},
                                  "evidencia": ev["enlaces"], "fecha_posteo": ev["ultima"],
                                  "otras_menciones": {k: v["menciones"] for k, v in res["divisiones"].items() if k != div},
                                  "nota": "Abrí los posteos y confirmá que hablan del equipo del club en la temporada actual."},
                       texto_para_filtro=f"{u} {div}")
        cont["division"] += r == "nuevo"
    dias = res.get("dias_sin_publicar")
    if dest["tipo"] == "club" and dias is not None and dias > DIAS_INACTIVA:
        mes = datetime.now(timezone.utc).strftime("%Y-%m")
        r = o.proponer(AGENTE, "propuesta_cambio",
                       f"{dest['nombre']}: @{u} sin publicar hace {dias} días (último posteo {res['ultimo_posteo']})",
                       _cap(f"https://www.instagram.com/{u}/#inactiva-{mes}", {"cuenta": u, "ultimo": res["ultimo_posteo"], "mes": mes}),
                       club_id=cid,
                       propuesta={"accion": "solo_informativa", "fuente": "instagram_oficial", "fecha_posteo": res["ultimo_posteo"],
                                  "parametros": {"cuenta": u, "dias_sin_publicar": dias, "ultimo_posteo": res["ultimo_posteo"],
                                                 "nota": "Puede ser solo que el club usa otra red. Confirmá si sigue compitiendo "
                                                         "antes de cambiar su estado."}},
                       texto_para_filtro=u)
        cont["inactiva"] = int(r == "nuevo")
    for n in res["novedades"]:
        resumen = (f"Publicación de Instagram de @{u} del {n['fecha']}. "
                   f"El texto menciona: {', '.join(n['marcas'])}. Ver el posteo en el enlace.")
        r = o.proponer(AGENTE, "novedad_red", f"@{u} ({n['fecha']}): {', '.join(n['marcas'])}",
                       _cap(n["permalink"], {"cuenta": u, **n}), cid, iid,
                       {"plataforma": "instagram", "fecha_posteo": n["fecha"], "extracto": resumen, "origen": "api_meta",
                        "menciona_colecta": "colecta" in n["marcas"], "temas": n["marcas"]},
                       resumen)
        cont["novedad"] += r == "nuevo"
    return cont


def prueba():
    propia = graph(os.environ["IG_USER_ID"], "username").get("username")
    print(f"Cuenta llave: @{propia}")
    for u in [propia, "basquetadaptadofaba"]:
        try:
            res = analizar(leer_cuenta(u, propia))
            print(f"@{u}: OK | seguidores {res['seguidores']} | publicaciones {res['publicaciones']} | "
                  f"último posteo {res['ultimo_posteo']} | posteos 90 días {res['posteos_90d']} | "
                  f"divisiones {{{', '.join(f'{k}: {v['menciones']}' for k, v in res['divisiones'].items())}}} | "
                  f"novedades con marcas {len(res['novedades'])}")
        except ErrorMeta as e:
            print(f"@{u}: {e.estado} | {e}")
        time.sleep(PAUSA)


def main():
    if not os.environ.get("META_TOKEN") or not os.environ.get("IG_USER_ID"):
        raise SystemExit("Faltan los secrets META_TOKEN e IG_USER_ID.")
    if "--prueba" in sys.argv:
        return prueba()
    propia = graph(os.environ["IG_USER_ID"], "username").get("username")
    ej = o.db().table("agente_ejecuciones").insert({"agente": AGENTE, "objetivos": 0}).execute()
    ej_id = ej.data[0]["id"] if ej.data else None
    resumen = {"leidas": 0, "sin_acceso": 0, "otras": 0, "division": 0, "novedad": 0, "inactiva": 0, "estados": {}}
    cuentas = cuentas_a_leer()
    por_cuenta = {}                                  # una misma cuenta puede figurar en dos fichas: se lee una vez
    for dest in cuentas:
        por_cuenta.setdefault(dest["instagram"].lower(), []).append(dest)
    repetidas = {u: [d["slug"] for d in ds] for u, ds in por_cuenta.items() if len(ds) > 1}
    if repetidas:
        print("Cuentas cargadas en más de una ficha (¿clubes duplicados?):", repetidas)
    for u, destinos in por_cuenta.items():
        try:
            res = analizar(leer_cuenta(u, propia))
            guardar_foto(destinos[0], res, "ok")
            for dest in destinos:
                c = proponer(dest, res)
                for k in ("division", "novedad", "inactiva"):
                    resumen[k] += c.get(k, 0)
            resumen["leidas"] += 1
            estado = (f"ok | último posteo {res['ultimo_posteo']} | 90 días: {res['posteos_90d']} | divisiones "
                      f"{ {k: v['menciones'] for k, v in res['divisiones'].items()} }")
        except ErrorMeta as e:
            estado = e.estado
            guardar_foto(destinos[0], {}, e.estado, str(e)[:300])
            resumen["sin_acceso" if e.estado == "sin_acceso" else "otras"] += 1
            if e.estado in ("token_vencido", "limite_meta"):
                print(f"Se detiene: {e.estado} ({e})")
                break
        resumen["estados"][u] = estado.split(" |")[0]
        print(f"@{u} ({', '.join(d['slug'] for d in destinos)}): {estado}")
        time.sleep(PAUSA)
    if ej_id:
        o.db().table("agente_ejecuciones").update({"fin": o.ahora().isoformat(), "objetivos": len(cuentas),
                                                   "ok": resumen["leidas"], "errores": resumen["otras"],
                                                   "bloqueados": resumen["sin_acceso"], "detalle": resumen}).eq("id", ej_id).execute()
    resumen["cuentas_repetidas"] = repetidas
    print({k: v for k, v in resumen.items() if k not in ("estados", "cuentas_repetidas")})


if __name__ == "__main__":
    main()
