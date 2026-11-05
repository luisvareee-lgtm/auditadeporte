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


# ---------------------------------------------------------------- Divisiones de todos los clubes desde los posteos de FABA
GENERICOS = r"^(?:club atletico|club|instituto municipal del deporte|instituto municipal|escuela municipal de basquet adaptado|" \
            r"escuela municipal|municipalidad de|municipio de|asociacion civil|fundacion)\s+"


def alias_de_clubes(clubes: list) -> dict:
    """Formas en que un posteo puede nombrar a cada club. Un alias que sirve para dos clubes se descarta
    (por ejemplo "brown": Almirante Brown y Brown de Alta Gracia; "cilsa": Santa Fe y Boca)."""
    cand = {}
    for c in clubes:
        nom = c.get("nombre") or ""
        al = {o._norm(nom), o._norm(re.sub(r"\(.*?\)", "", nom)).strip(), o._norm(c["slug"].replace("-", " "))}
        al |= {o._norm(x) for x in re.findall(r"\(([^)]+)\)", nom)}
        al |= {o._norm(t) for t in re.findall(r"\b[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-z.]*[A-ZÁÉÍÓÚÑ]\b", nom) if len(t.replace(".", "")) >= 3
               and sum(ch.isupper() for ch in t) >= 3}                       # siglas: CEDIMA, CROL, Fu.Di.Tuc
        sin_gen = re.sub(GENERICOS, "", o._norm(re.sub(r"\(.*?\)", "", nom))).strip()
        if len(sin_gen) >= 5:
            al.add(sin_gen)                                                  # "almirante brown", "avellaneda"
        if c.get("instagram"):
            al.add("@" + c["instagram"].lower())
        for a in al:
            a = a.replace(".", "")                             # el texto se compara sin puntos
            if len(a) >= 3:
                cand.setdefault(a, set()).add(c["id"])
    return {a: next(iter(ids)) for a, ids in cand.items() if len(ids) == 1}


def divisiones_desde_faba(cuenta: dict, clubes: list, hoy: date = None) -> dict:
    """{club_id: {division: {menciones, ultima, enlaces}}} según los posteos de FABA del último año.
    Un posteo cuenta para una división solo si nombra una sola división (si nombra varias, es ambiguo)."""
    hoy = hoy or datetime.now(timezone.utc).date()
    alias = alias_de_clubes(clubes)
    patrones = [(re.compile(r"(?<![a-z0-9@._])" + re.escape(a) + r"(?![a-z0-9_])"), cid) for a, cid in
                sorted(alias.items(), key=lambda kv: -len(kv[0]))]
    out = {}
    for p in (cuenta.get("media") or {}).get("data") or []:
        if not p.get("timestamp") or not p.get("permalink"):
            continue
        f = _fecha(p["timestamp"])
        if (hoy - f).days > 365:
            continue
        txt = o._norm(p.get("caption") or "").replace(".", "")
        divs = [d for d, rx in DIVISIONES.items() if re.search(rx, txt)]
        if len(divs) != 1:
            continue
        for cid in {cid for rx, cid in patrones if rx.search(txt)}:
            d = out.setdefault(cid, {}).setdefault(divs[0], {"menciones": 0, "ultima": None, "enlaces": []})
            d["menciones"] += 1
            d["ultima"] = max(d["ultima"] or f.isoformat(), f.isoformat())
            if len(d["enlaces"]) < 5:
                d["enlaces"].append(p["permalink"])
    return out


def proponer_divisiones_faba(por_club: dict, clubes: list) -> int:
    n = 0
    por_id = {c["id"]: c for c in clubes}
    for cid, divs in por_club.items():
        c = por_id.get(cid)
        div = division_probable(divs)
        if not c or not div or divs[div]["menciones"] < 2:          # una sola mención no alcanza
            continue
        if div == c.get("division") and c.get("estado_afiliacion") == "activo":
            continue
        ev = divs[div]
        r = o.proponer(AGENTE, "propuesta_cambio",
                       f"{c['nombre']}: FABA lo nombra en {div} división ({ev['menciones']} posteos, último {ev['ultima']})",
                       _cap(ev["enlaces"][0] + "#club-" + c["slug"], {"club": c["slug"], "division": div, **ev}), club_id=cid,
                       propuesta={"accion": "actualizar_division_club", "fuente": "instagram_faba",
                                  "parametros": {"division": div, "fuente_url": ev["enlaces"][0], "fecha": ev["ultima"]},
                                  "actual": {"division": c.get("division"), "estado_afiliacion": c.get("estado_afiliacion")},
                                  "evidencia": ev["enlaces"], "fecha_posteo": ev["ultima"],
                                  "otras_menciones": {k: v["menciones"] for k, v in divs.items() if k != div},
                                  "nota": "Detectado por nombre en posteos de FABA. Abrí los enlaces y confirmá que se refieren a este club."},
                       texto_para_filtro=f"{c['slug']} {div}")
        n += r == "nuevo"
    return n


# ---------------------------------------------------------------- Contraste colecta / fuentes oficiales relevadas
def contraste_colecta(dest: dict, n: dict, cap_post: o.Captura) -> str:
    """Dictamen de contraste objetivo (Patrón A): una colecta publicada por el club frente a lo que
    AuditaDeporte relevó en fuentes oficiales de esa entidad. Sin calificativos. La ausencia en NUESTRAS
    fuentes no prueba ausencia en la realidad: el texto lo dice y, si no hay fuentes, propone cómo cubrir el hueco."""
    cid = dest["id"]
    fuentes = o.db().table("fuentes_monitoreadas").select("nombre,tipo,estado,ultima_revision").eq("club_id", cid).execute().data or []
    desde = (date.fromisoformat(n["fecha"]) - timedelta(days=365)).isoformat()
    docs = [d for d in (o.db().table("documentos_fuente").select("titulo,expediente_o_norma,url_fuente,portal_origen,fecha_captura")
                        .eq("club_id", cid).execute().data or []) if (d.get("fecha_captura") or "")[:10] >= desde]
    hoy = datetime.now(timezone.utc).date().isoformat()
    motivo = "convocatoria a colecta, rifa o pedido de fondos" + (" vinculada a un viaje o traslado" if "viaje" in n["marcas"] else "")
    hecho = (f"Hecho relevado: publicación de @{dest['instagram']} de fecha {n['fecha']} (SHA-256 {cap_post.sha256[:16]}…) "
             f"registra una {motivo}.")
    activas = [f for f in fuentes if f.get("estado") == "activa"]
    if not activas:
        contraste = (f"Contraste: a la fecha de corte ({hoy}) AuditaDeporte no tiene fuentes oficiales activas relevadas "
                     f"para {dest['nombre']}; no es posible contrastar. Para cubrirlo: cargar como fuente el boletín oficial "
                     f"de la jurisdicción o iniciar un pedido de acceso a la información pública.")
        estado = "sin_fuentes"
    elif docs:
        lista = "; ".join(f"{d['titulo'][:80]}" + (f" ({d['expediente_o_norma']})" if d.get("expediente_o_norma") else "")
                          for d in docs[:5])
        contraste = (f"Contraste: a la fecha de corte ({hoy}), en las {len(activas)} fuentes oficiales relevadas para "
                     f"{dest['nombre']} obran {len(docs)} documento(s) de los 12 meses previos: {lista}. "
                     f"Verificar si alguno corresponde al gasto mencionado en la publicación.")
        estado = "con_documentos"
    else:
        tipos = ", ".join(sorted({f["tipo"] for f in activas}))
        contraste = (f"Contraste: a la fecha de corte ({hoy}), en las {len(activas)} fuentes oficiales relevadas para "
                     f"{dest['nombre']} ({tipos}) no obra documento de los 12 meses previos vinculado a asignación de fondos, "
                     f"viáticos o contratación de transporte. La falta de registro en estas fuentes no acredita que el acto "
                     f"no exista: corresponde confirmarlo en la fuente o mediante pedido de acceso a la información.")
        estado = "sin_documentos"
    dictamen = f"{hecho} {contraste}"
    r = o.proponer(AGENTE, "propuesta_cambio", f"Contraste: colecta de {dest['nombre']} ({n['fecha']}) frente a fuentes oficiales relevadas",
                   _cap(n["permalink"] + "#contraste-" + hoy[:7], {"post": n, "fuentes": len(activas), "docs": len(docs), "corte": hoy}),
                   club_id=cid,
                   propuesta={"accion": "solo_informativa", "fuente": "contraste_colecta", "fecha_posteo": n["fecha"],
                              "parametros": {"dictamen": dictamen, "resultado": estado, "publicacion": n["permalink"],
                                             "fuentes_activas": len(activas), "documentos_12_meses": len(docs),
                                             "fecha_corte": hoy}},
                   texto_para_filtro=dictamen)
    return r


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
    clubes = o.db().table("clubes").select("id,slug,nombre,instagram,division,estado_afiliacion,publicado").execute().data or []
    clubes = [c for c in clubes if c.get("publicado") is not False and c.get("estado_afiliacion") != "baja"]   # los dados de baja no se leen
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
    cont = {"division": 0, "novedad": 0, "inactiva": 0, "contraste": 0}
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
        if dest["tipo"] == "club" and "colecta" in n["marcas"]:
            cont["contraste"] = cont.get("contraste", 0) + (contraste_colecta(dest, n, _cap(n["permalink"], {"cuenta": u, **n})) == "nuevo")
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
    resumen = {"leidas": 0, "sin_acceso": 0, "otras": 0, "division": 0, "novedad": 0, "inactiva": 0, "contraste": 0,
               "division_faba": 0, "estados": {}}
    todos_clubes = o.db().table("clubes").select("id,slug,nombre,instagram,division,estado_afiliacion,publicado").execute().data or []
    todos_clubes = [c for c in todos_clubes if c.get("publicado") is not False]
    cuentas = cuentas_a_leer()
    por_cuenta = {}                                  # una misma cuenta puede figurar en dos fichas: se lee una vez
    for dest in cuentas:
        por_cuenta.setdefault(dest["instagram"].lower(), []).append(dest)
    repetidas = {u: [d["slug"] for d in ds] for u, ds in por_cuenta.items() if len(ds) > 1}
    if repetidas:
        print("Cuentas compartidas por más de una ficha (se leen una vez; revisar si no es la misma organización):", repetidas)
    for u, destinos in por_cuenta.items():
        try:
            crudo = leer_cuenta(u, propia)
            res = analizar(crudo)
            guardar_foto(destinos[0], res, "ok")
            for dest in destinos:
                c = proponer(dest, res)
                for k in ("division", "novedad", "inactiva", "contraste"):
                    resumen[k] += c.get(k, 0)
                if dest["tipo"] == "inst" and dest["slug"] == "faba":
                    resumen["division_faba"] += proponer_divisiones_faba(divisiones_desde_faba(crudo, todos_clubes), todos_clubes)
            del crudo                                        # los textos de los posteos no se conservan
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
