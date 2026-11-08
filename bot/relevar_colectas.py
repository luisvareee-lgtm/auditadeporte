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
LLAMADAS_POR_CORRIDA = 60             # por corrida, cada 3 horas: Meta frena antes de las 200 por hora con cuentas grandes
DESDE_TOTAL = date(2010, 1, 1)        # barrido exhaustivo: toda la historia de la cuenta
AQUI = os.path.dirname(os.path.abspath(__file__))

RE_COLECTA = re.compile(r"\b(rifas?|bonos? contribucion|colectas?|alias|cbu|cvu|ayudanos|ayudenos|donacion(es)?|dona(r|nos)?|"
                        r"aporte solidario|campana solidaria|vaquita|mercado pago|necesitamos (juntar|recaudar)|recaudar|sorteos?|"
                        r"a beneficio|beneficio para|pena solidaria|bingo|gofundme|cafecito|link de pago|buscamos (sponsors?|patrocin\w*)|"
                        r"venta solidaria|se venden|vendemos)\b")
# cómo se pide la plata
TIPOS_PEDIDO = {
    "rifa_sorteo": r"\b(rifas?|sorteos?|bonos? contribucion|numeros? a la venta)\b",
    "venta_comida": r"\b(empanadas?|pizzas?|locro|pastelitos?|tortas?|choripan\w*|asado|pollos?|bonos? de comida)\b",
    "evento": r"\b(pena|bingo|cena|show|torneo de truco|festival|kermes\w*|evento solidario|partido a beneficio)\b",
    "transferencia": r"\b(alias|cbu|cvu|mercado pago|transferencia)\b",
    "campana_online": r"\b(gofundme|cafecito|link de pago|vaki|campana online|https?://\S*(gofundme|cafecito|mpago|mercadopago)\S*)\b",
    "venta_merch": r"\b(remeras?|buzos?|gorras?|merch\w*|camisetas? a la venta)\b",
    "pedido_empresas": r"\b(sponsors?|patrocin\w*|empresas?|comercios?|pymes?)\b",
    "pedido_estado": r"\b(municipio|municipalidad|intendente|secretaria de deportes|subsecretaria|gobierno|enard)\b",
}
# a quién se le pide
DESTINATARIOS = {
    "personas": r"\b(todos|cada uno|tu aporte|colabora(r|s)?|compart\w*|cualquier monto)\b",
    "empresas": TIPOS_PEDIDO["pedido_empresas"],
    "estado": TIPOS_PEDIDO["pedido_estado"],
}
MESES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"], 1)}
RE_LIMITE = re.compile(r"\b(?:antes del?|hasta el|para el|el)\s+(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
                       r"octubre|noviembre|diciembre)\b")
# tiene que haber un pedido de plata: un sorteo de grupos, un concurso o una inscripción a un curso no son colectas
RE_DINERO = re.compile(r"\b(rifas?|bonos? contribucion|colectas?|alias|cbu|cvu|mercado pago|transferencia|donacion(es)?|dona(r|nos|ndo)|"
                       r"aport\w*|colabor\w*|ayud(a|anos|enos)|recaud\w*|juntar|necesitamos|a beneficio|solidari\w*|sponsors?|"
                       r"patrocin\w*|gofundme|cafecito|link de pago|vendemos|se venden|venta)\b|\$|u\$s|usd")
RE_FALSO = re.compile(r"\b(se sorteo|sorteo de (la )?(fase|grupos|zonas|fixture)|ganate|participa del sorteo|curso|capacitacion|clinica)\b")
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


def clasificar(caption: str, fecha: str = None):
    """None si no es una colecta (o si habla de la salud de una persona). Si lo es: finalidades, cómo se pide,
    a quién, torneos, montos y fecha límite (si la dice)."""
    t = o._norm(caption or "")
    if not RE_COLECTA.search(t) or RE_SALUD.search(t) or not RE_DINERO.search(t):
        return None
    if RE_FALSO.search(t) and not re.search(r"\b(rifas?|colectas?|recaud\w*|donacion(es)?)\b", t):
        return None
    fin = [k for k, rx in FINALIDADES.items() if re.search(rx, t)] or ["general"]
    tipos = [k for k, rx in TIPOS_PEDIDO.items() if re.search(rx, t)] or ["otro"]
    dest = [k for k, rx in DESTINATARIOS.items() if re.search(rx, t)] or ["personas"]
    tor = [k for k, rx in TORNEOS.items() if re.search(rx, t)]
    limite = None
    ml = RE_LIMITE.search(t)
    if ml and fecha:
        try:
            anio = int(fecha[:4]); d = date(anio, MESES[ml.group(2)], int(ml.group(1)))
            limite = (d if d >= date.fromisoformat(fecha[:10]) else date(anio + 1, d.month, d.day)).isoformat()
        except ValueError:
            limite = None
    montos = []
    for m in RE_MONTO.finditer(caption or ""):
        x = _monto(m)
        if x["valor"] >= 1000 and x not in montos:
            montos.append(x)
    return {"finalidades": fin, "tipos_pedido": tipos, "destinatarios": dest, "torneos": tor, "montos": montos[:4],
            "fecha_limite": limite}


# Otras señales útiles (no colectas): quién apoya, viajes, equipamiento, reclamos y avisos de torneo.
SENALES = {
    "apoyo_estado": r"\b(gracias|agradec\w*)\b.{0,80}\b(municipio|municipalidad|intendente|instituto municipal|secretaria|subsecretaria|gobierno|enard)\b",
    "apoyo_empresas": r"\b(gracias|agradec\w*)\b.{0,80}\b(sponsors?|patrocin\w*|empresas?|comercios?|marcas?|auspicia\w*)\b|\bnuestros sponsors\b",
    "viaje": r"\b(viajamos|viaje a|partimos (hacia|rumbo)|llegamos a|rumbo a|de gira)\b",
    "equipamiento_nuevo": r"\b(nuevas? sillas?|entrega de sillas?|recibimos (las|nuevas)|nueva indumentaria|nuevas camisetas)\b",
    "reclamo": r"\b(sin apoyo|falta de apoyo|no tenemos sillas|sillas rotas|nadie nos ayuda|abandon\w*|reclam\w*)\b",
    "promesa_estado": r"\b(secretaria|subsecretaria) de deportes?\b.{0,120}\b(prometi\w*|compromet\w*|iban a|no lleg\w*|todavia no|nunca lleg\w*|esperamos)\b|"
                      r"\b(prometi\w*|compromet\w*|iban a|no lleg\w*)\b.{0,120}\b(secretaria|subsecretaria) de deportes?\b",
    "beca_atrasada": r"\bbecas?\b.{0,80}\b(atrasad\w*|adeud\w*|impag\w*|no (cobr|pag|lleg|deposit)\w*|sin cobrar|demor\w*|recort\w*|"
                     r"dad[oa]s? de baja|suspend\w*|congelad\w*)\b|\b(no cobramos|adeudan|nos deben|seguimos sin cobrar)\b.{0,60}\bbecas?\b",
    "convocatoria_torneo": r"\b(confirmad[oa]s?|fixture|cronograma|sede)\b.{0,60}\b(torneo|fecha|liga|nacional|cuadrangular)\b",
}


def senales(caption: str) -> list:
    t = o._norm(caption or "")
    if RE_SALUD.search(t):
        return []
    return [k for k, rx in SENALES.items() if re.search(rx, t)]


def _progreso(cuenta):
    try:
        r = o.db().table("barrido_redes").select("*").eq("cuenta", cuenta).execute().data
        return r[0] if r else {}
    except Exception:                 # sin db/24: barre desde el principio y no guarda avance
        return {}


def _guardar_progreso(fila):
    try:
        o.db().table("barrido_redes").upsert([fila], on_conflict="cuenta").execute()
    except Exception:
        pass


def barrer(usuario: str, propia: str, desde: date, presupuesto: list, prueba=False):
    """Recorre TODOS los posteos de la cuenta (50 por consulta). Clasifica cada página en el momento y descarta el
    texto. Guarda el cursor en barrido_redes para seguir en la próxima corrida si se agota el presupuesto de consultas.
    Una vez completo, las corridas siguientes solo leen lo nuevo. presupuesto = [consultas que quedan] (se descuenta)."""
    import actualidad_redes as ar
    ig, campos = os.environ["IG_USER_ID"], "timestamp,permalink,caption,media_type,media_url"
    prog = {} if prueba else _progreso(usuario.lower())
    completo, after = bool(prog.get("completo")), (None if prog.get("completo") else prog.get("cursor"))
    hasta_fecha = date.fromisoformat(prog["mas_nuevo"]) if completo and prog.get("mas_nuevo") else None
    leidos, mas_nuevo, posts_clasif = int(prog.get("posts_leidos") or 0), prog.get("mas_nuevo"), []
    corte = None
    lim = 50
    while presupuesto[0] > 0:
        pag = f".after({after})" if after else ""
        presupuesto[0] -= 1
        try:
            if usuario.lower() == (propia or "").lower():
                d = ar.graph(ig, f"media{pag}.limit({lim}){{{campos}}}").get("media") or {}
            else:
                d = (ar.graph(ig, f"business_discovery.username({usuario}){{media{pag}.limit({lim}){{{campos}}}}}")
                     .get("business_discovery") or {}).get("media") or {}
        except ar.ErrorMeta as e:
            if e.estado == "error" and lim > 10 and re.search(r"timed out|Extra data|Expecting|reduce the amount", str(e)):
                lim = max(10, lim // 2); continue      # respuesta demasiado grande (cuentas con textos largos): páginas más chicas
            if e.estado == "error" and after and after == prog.get("cursor"):
                after = None; continue          # cursor guardado vencido: se empieza de nuevo
            if e.estado != "limite_meta" or not leidos:
                raise
            corte = str(e)                      # límite de Meta: se guarda el avance y se sigue en la próxima corrida
            break
        posts = [p for p in d.get("data") or [] if p.get("timestamp")]
        leidos += len(posts)
        for p in posts:
            f = ar._fecha(p["timestamp"])
            mas_nuevo = max(mas_nuevo or f.isoformat(), f.isoformat())
            if f >= desde and (not hasta_fecha or f >= hasta_fecha):
                cap = p.get("caption") or ""
                import transcribir as tr
                if tr.conviene(p):                 # el audio del video se suma al texto solo para clasificar; no se guarda
                    hablado = tr.transcribir(p["media_url"])
                    if hablado:
                        cap = f"{cap}\n{hablado}"
                        print(f"  video transcripto: {p.get('permalink')}", flush=True)
                posts_clasif.append({"timestamp": p["timestamp"], "permalink": p.get("permalink"), "caption": cap})
        nuevo = ((d.get("paging") or {}).get("cursors") or {}).get("after")
        after = nuevo if nuevo and nuevo != after else None
        viejo = posts and ar._fecha(posts[-1]["timestamp"]) < (hasta_fecha or desde)
        if not posts or not after or viejo:
            completo = completo or not after or viejo
            after = None
            break
        time.sleep(ar.PAUSA)
    if not prueba:
        _guardar_progreso({"cuenta": usuario.lower(), "cursor": after, "completo": completo, "posts_leidos": leidos,
                           "mas_nuevo": mas_nuevo, "actualizado": datetime.now(timezone.utc).isoformat()})
    if corte:
        presupuesto[0] = 0                      # no seguir con otras cuentas en esta corrida
        print(f"  {usuario}: límite de Meta, avance guardado ({corte[:120]})", flush=True)
    return posts_clasif, completo


FABA_BASE = "https://basquetadaptado.com.ar"
PALABRAS_WEB = ["rifa", "colecta", "ayuda", "donacion", "alias", "sorteo", "beneficio", "solidaria", "sponsor", "recaudar", "colaborar", "financiamiento"]


def _items_wp(kw, desde):
    """Busca en el sitio de FABA. La API REST está apagada (/wp-json da 404), así que prueba ?rest_route= y después
    el canal RSS de búsqueda que trae WordPress (?s=palabra&feed=rss2). Respeta robots.txt (o.capturar)."""
    import urllib.parse
    from xml.etree import ElementTree as ET
    q = {"search": kw, "per_page": 50, "after": f"{desde.isoformat()}T00:00:00", "_fields": "date,link,title,content"}
    c = o.capturar(FABA_BASE + "/?" + urllib.parse.urlencode({"rest_route": "/wp/v2/posts", **q}))
    if c.http == 200 and c.contenido[:1] == b"[":
        try:
            return [{"fecha": it.get("date", "")[:10], "link": it.get("link"),
                     "html": (it.get("title") or {}).get("rendered", "") + " " + (it.get("content") or {}).get("rendered", "")}
                    for it in json.loads(c.contenido.decode("utf-8", "ignore"))]
        except ValueError:
            pass
    out = []
    for pag in range(1, 6):
        c = o.capturar(FABA_BASE + "/?" + urllib.parse.urlencode({"s": kw, "feed": "rss2", "paged": pag}))
        if c.http != 200 or not c.contenido:
            if pag == 1:
                print(f"  faba web '{kw}': {c.http} {c.motivo}")
            break
        try:
            raiz = ET.fromstring(c.contenido)
        except ET.ParseError:
            break
        ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
        nuevos = 0
        for it in raiz.iter("item"):
            try:
                f = datetime.strptime((it.findtext("pubDate") or "")[:25].strip(), "%a, %d %b %Y %H:%M:%S").date()
            except ValueError:
                continue
            if f < desde:
                continue
            nuevos += 1
            out.append({"fecha": f.isoformat(), "link": it.findtext("link"),
                        "html": (it.findtext("title") or "") + " " + (it.findtext("content:encoded", namespaces=ns) or it.findtext("description") or "")})
        if not nuevos:
            break
        time.sleep(1)
    return out


def leer_faba_web(desde: date):
    """Noticias del sitio oficial de FABA que mencionan pedidos de fondos (sin clave: solo lo que el sitio publica)."""
    import html
    vistos, out = set(), []
    for kw in PALABRAS_WEB:
        for it in _items_wp(kw, desde):
            if not it.get("link") or it["link"] in vistos:
                continue
            vistos.add(it["link"])
            texto = html.unescape(re.sub(r"<[^>]+>", " ", it["html"]))
            out.append({"timestamp": it["fecha"], "permalink": it["link"], "caption": texto, "fuente": "faba_web"})
        time.sleep(1)
    print(f"  faba web: {len(out)} noticias con alguna palabra clave")
    return out


# Organizaciones que viven de campañas de donación: sus pedidos son su forma de financiarse, no colectas de deportistas
# o equipos por falta de fondos. Se leen igual (otras señales), pero no cuentan como colectas.
RECAUDACION_PROPIA = {"cilsaong": "ONG que se financia con campañas de donación permanentes"}


def senales_cuenta(usuario, nombre, tipo, posts):
    """Publicaciones con señales útiles que no son colectas (quién apoya, viajes, reclamos, avisos de torneo)."""
    out = []
    for p in posts:
        sn = senales(p.get("caption"))
        if tipo == "institucion":           # ENARD, COPAR y otras agradecen a sus sponsors en cada posteo: no es un dato nuevo
            sn = [x for x in sn if x != "apoyo_empresas"]
        if sn and p.get("permalink") and not clasificar(p.get("caption"), p.get("timestamp")):
            t = o._norm(p.get("caption") or "")
            out.append({"cuenta": usuario.lower(), "nombre_cuenta": nombre, "tipo_cuenta": tipo, "fecha": p["timestamp"][:10],
                        "permalink": p["permalink"], "senales": sn, "torneos": [k for k, rx in TORNEOS.items() if re.search(rx, t)]})
    return out


def relevar_cuenta(usuario, nombre, tipo, posts):
    filas = []
    for p in posts:
        c = clasificar(p.get("caption"), p.get("timestamp"))
        if not c or not p.get("permalink"):
            continue
        filas.append({"cuenta": usuario.lower(), "nombre_cuenta": nombre, "tipo_cuenta": tipo, "fecha": p["timestamp"][:10],
                      "permalink": p["permalink"], "fuente": p.get("fuente", "instagram"), **c})
    return filas


def agregar(filas: list) -> dict:
    por_anio, por_fin, por_torneo, por_cuenta, montos, por_tipo, por_dest = {}, {}, {}, {}, {}, {}, {}
    for f in filas:
        a = f["fecha"][:4]
        por_anio[a] = por_anio.get(a, 0) + 1
        for x in f["finalidades"]:
            por_fin[x] = por_fin.get(x, 0) + 1
        for x in f["torneos"]:
            por_torneo[x] = por_torneo.get(x, 0) + 1
        for x in f.get("tipos_pedido") or []:
            por_tipo[x] = por_tipo.get(x, 0) + 1
        for x in f.get("destinatarios") or []:
            por_dest[x] = por_dest.get(x, 0) + 1
        k = f["nombre_cuenta"]
        c = por_cuenta.setdefault(k, {"cuenta": f["cuenta"], "tipo": f["tipo_cuenta"], "colectas": 0, "ultima": None, "finalidades": {}})
        c["colectas"] += 1
        c["ultima"] = max(c["ultima"] or f["fecha"], f["fecha"])
        for x in f["finalidades"]:
            c["finalidades"][x] = c["finalidades"].get(x, 0) + 1
        for m in f["montos"]:
            montos.setdefault(m["moneda"], []).append(m["valor"])
    return {"total": len(filas), "por_anio": dict(sorted(por_anio.items())), "por_finalidad": por_fin, "por_torneo": por_torneo,
            "por_tipo_pedido": por_tipo, "por_destinatario": por_dest,
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
    # primero federación, comité y selecciones (son las que lanzan las colectas grandes), después los clubes
    return sorted(res, key=lambda x: {"institucion": 0, "seleccion": 1}.get(x[2], 2))


def contraste(colectas: list, cuenta_a_juris: dict, ejecuciones: list) -> dict:
    """Para cada colecta de un club, la ejecución de Deporte de su municipio más cercana ANTES de la fecha de la colecta
    (si no hay, la primera posterior, marcada así). Dos hechos con su fuente, uno al lado del otro: no se opina.
    Devuelve {permalink: {...}}. Solo usa ejecuciones publicadas por una persona desde el panel."""
    por_juris = {}
    for e in ejecuciones:
        if e.get("deporte") and e.get("hasta"):
            por_juris.setdefault(e["juris_slug"], []).append(e)
    out = {}
    for c in colectas:
        j = cuenta_a_juris.get((c.get("cuenta") or "").lower())
        es = sorted(por_juris.get(j) or [], key=lambda e: e["hasta"])
        if not es:
            continue
        antes = [e for e in es if e["hasta"] <= c["fecha"]]
        e, momento = (antes[-1], "antes") if antes else (es[0], "despues")
        d = e["deporte"]
        out[c["permalink"]] = {"juris_slug": j, "hasta": e["hasta"], "momento": momento, "linea": d.get("linea"),
                               "vigente": d.get("vigente"), "devengado": d.get("devengado"), "pagado": d.get("pagado"),
                               "porcentaje_devengado": d.get("porcentaje_devengado"), "fuente": e.get("url")}
    return out


def _cuenta_a_juris(cli):
    """Cuenta de Instagram del club → municipio (según la lista de clubes de cada jurisdicción en datos/transparencia.json)."""
    try:
        t = json.load(open(os.path.join(AQUI, "..", "datos", "transparencia.json"), encoding="utf-8"))
        clubes = cli.table("clubes").select("nombre,instagram").execute().data or []
    except Exception:
        return {}
    nombre_a_juris = {}
    for j in t.get("jurisdicciones") or []:
        if j["slug"].startswith("muni-"):
            for n in j.get("clubes") or []:
                nombre_a_juris[n] = j["slug"]
    return {c["instagram"].lower(): nombre_a_juris[c["nombre"]] for c in clubes if c.get("instagram") and c["nombre"] in nombre_a_juris}


def publicar(cli=None):
    """datos/colectas.json: solo agregados y enlaces a posteos de cuentas oficiales."""
    cli = cli or o.db()
    try:
        filas = cli.table("colectas_relevadas").select("cuenta,nombre_cuenta,tipo_cuenta,fecha,permalink,finalidades,torneos,montos,"
                                                       "tipos_pedido,destinatarios,fecha_limite,fuente").eq("revisada", True).execute().data or []
    except Exception:                         # antes de db/22
        filas = cli.table("colectas_relevadas").select("cuenta,nombre_cuenta,tipo_cuenta,fecha,permalink,finalidades,torneos,montos") \
            .execute().data or []
    import patrones_colectas as pc
    try:
        ejec = cli.table("ejecuciones_presupuestarias").select("juris_slug,hasta,deporte,url").eq("publicado", True) \
            .eq("tipo", "gastos").execute().data or []
    except Exception:
        ejec = []
    cx = contraste(filas, _cuenta_a_juris(cli), ejec)
    try:
        pubs = cli.table("publicaciones_relevantes").select("nombre_cuenta,tipo_cuenta,fecha,permalink,senales") \
            .eq("revisada", True).execute().data or []
    except Exception:
        pubs = []
    por_mes = {f"{m:02d}": 0 for m in range(1, 13)}
    for f in filas:
        por_mes[f["fecha"][5:7]] = por_mes.get(f["fecha"][5:7], 0) + 1
    hitos = sorted([{"fecha": p["fecha"], "cuenta": p["nombre_cuenta"], "senal": sn, "permalink": p["permalink"]}
                    for p in pubs for sn in p["senales"] if sn in ("promesa_estado", "beca_atrasada", "reclamo", "apoyo_estado")],
                   key=lambda x: x["fecha"])
    datos = {"actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%d"), **agregar(filas), "patrones": pc.patrones(filas),
             "por_mes": por_mes, "hitos_estado": hitos[-200:],
             "recientes": [{**{k: f.get(k) for k in ("nombre_cuenta", "tipo_cuenta", "fecha", "permalink", "finalidades", "torneos",
                                                     "tipos_pedido", "montos")},
                            "presupuesto_municipio": cx.get(f["permalink"])}
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
    desde = date.fromisoformat(sys.argv[sys.argv.index("--desde") + 1]) if "--desde" in sys.argv else DESDE_TOTAL
    prueba = "--prueba" in sys.argv
    propia = ar.graph(os.environ["IG_USER_ID"], "username").get("username")
    todas, estados = [], {}
    try:                                     # el sitio de FABA no depende del permiso de Meta
        web = leer_faba_web(desde)
        fw = relevar_cuenta("faba_web", "FABA (sitio oficial)", "institucion", web)
        del web
        todas += fw
        estados["faba_web"] = f"ok ({len(fw)} colectas)"
        for f in fw:                          # noticias públicas de la federación: se pueden listar
            print("  FABA:", f["fecha"], f["permalink"], f["finalidades"], f["tipos_pedido"], f["torneos"])
    except Exception as e:
        estados["faba_web"] = f"error: {str(e)[:80]}"
    presupuesto, otras = [LLAMADAS_POR_CORRIDA], []
    if not prueba:                                   # lo que ya se había guardado de esas cuentas sin revisar, se quita
        for cta in RECAUDACION_PROPIA:
            try:
                o.db().table("colectas_relevadas").delete().eq("cuenta", cta).eq("revisada", False).execute()
                o.db().table("publicaciones_relevantes").delete().eq("cuenta", "enardinfo").eq("revisada", False) \
                    .eq("senales", "{apoyo_empresas}").execute()
            except Exception as e:
                print("no se pudo limpiar", cta, str(e)[:80])
    for usuario, nombre, tipo in cuentas():
        if presupuesto[0] <= 0:
            estados[usuario] = "pendiente (sigue en la próxima corrida)"; continue
        try:
            posts, completo = barrer(usuario, propia, desde, presupuesto, prueba)
            filas = [] if usuario.lower() in RECAUDACION_PROPIA else relevar_cuenta(usuario, nombre, tipo, posts)
            otras += senales_cuenta(usuario, nombre, tipo, posts)
            del posts                                  # los textos no se conservan
            todas += filas
            estados[usuario] = f"ok ({len(filas)} colectas{'' if completo else ', barrido a medias'})"
        except ar.ErrorMeta as e:
            estados[usuario] = f"{e.estado}: {str(e)[:160]}"
            if e.estado in ("limite_meta", "token_vencido"):
                break
        time.sleep(ar.PAUSA)
    sen = {}
    for x in otras:
        for k in x["senales"]:
            sen[k] = sen.get(k, 0) + 1
    print("OTRAS SEÑALES:", json.dumps(sen, ensure_ascii=False), "| consultas usadas:", LLAMADAS_POR_CORRIDA - presupuesto[0])
    if not prueba and otras:
        try:
            o.db().table("publicaciones_relevantes").upsert(otras, on_conflict="permalink", ignore_duplicates=True).execute()
        except Exception as e:
            print("sin db/24 (publicaciones_relevantes):", str(e)[:120])
    print("CUENTAS:", json.dumps(estados, ensure_ascii=False))
    print("AGREGADO:", json.dumps(agregar(todas), ensure_ascii=False))
    import patrones_colectas as pc
    print("PATRONES:\n" + pc.resumen_texto(pc.patrones(todas)))
    if prueba or not todas:
        return
    try:                                     # entran sin revisar (db/22): una persona las aprueba en el panel
        o.db().table("colectas_relevadas").upsert(todas, on_conflict="permalink").execute()
        print("guardadas:", len(todas))
    except Exception as e:
        print("sin db/22, se guardan solo las columnas de db/21:", str(e)[:120])
        viejas = [{k: f[k] for k in ("cuenta", "nombre_cuenta", "tipo_cuenta", "fecha", "permalink", "finalidades", "torneos", "montos")}
                  for f in todas if "instagram.com" in f["permalink"]]
        try:
            if viejas:
                o.db().table("colectas_relevadas").upsert(viejas, on_conflict="permalink").execute()
        except Exception as e2:
            print("no se pudo guardar (¿falta db/21?):", str(e2)[:150])


if __name__ == "__main__":
    main()
