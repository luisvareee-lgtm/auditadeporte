"""Especialistas de AuditaDeporte: cada uno mira un frente distinto y PROPONE un cambio concreto con evidencia.
La propuesta pasa por la mesa (votos) y llega al panel. Solo si una persona la aprueba, la base ejecuta
la acción (lista cerrada en db/09: aprobar_propuesta). Ningún especialista escribe en tablas públicas.

  analista_rse        Novedades aprobadas que mencionan colecta/rifa -> borrador de pliego RSE (no se publica solo).
  seguimiento_pedidos Pedidos de información vencidos -> borrador de reclamo para que lo envíe una persona.
  control_vigencia    Autoridades publicadas que ya no aparecen en su fuente, o datos de más de un año.
  delegado_datos      Contactos de casos cerrados con más de 180 días -> propuesta de borrado (minimización).
  analista_cruces     Mismo expediente en 2 o más fuentes -> aviso para investigar con documentos.
  guardian_seguridad  Claves secretas en el repo o en el sitio, tablas privadas legibles con la clave pública,
                      cabeceras de seguridad faltantes. Si encuentra algo crítico, el workflow termina en rojo.
"""
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import orquestador_bots_audita as o

SITIO = (os.environ.get("SITIO_URL") or "https://luisvareee-lgtm.github.io/auditadeporte/").rstrip("/") + "/"
REPO = (os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "luisvareee-lgtm/auditadeporte"))
RETENCION_DIAS = 180
TABLAS_PRIVADAS = ["cola_revision", "agente_votos", "agente_ejecuciones", "tips", "postulaciones_rse",
                   "presentaciones_club", "administradores", "panel_acciones", "fuentes_monitoreadas", "fuente_urls_vistas"]
CABECERAS = ["content-security-policy", "x-content-type-options", "referrer-policy", "strict-transport-security"]
RE_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
RE_SB_SECRET = re.compile(r"sb_secret_[A-Za-z0-9_-]{10,}")


def proponer_cambio(agente, titulo, url_evidencia, accion, parametros=None, club_id=None, inst_id=None,
                    texto="", extra=None, clave_unica=None):
    """Arma la propuesta y la pasa por la mesa. El hash identifica la propuesta: la misma no se repite."""
    cuerpo = json.dumps({"accion": accion, "parametros": parametros or {}, "clave": clave_unica or titulo,
                         "url": url_evidencia}, sort_keys=True, ensure_ascii=False).encode()
    cap = o.Captura(url_evidencia, 200, cuerpo, hashlib.sha256(cuerpo).hexdigest())
    prop = {"accion": accion, "parametros": parametros or {}, **(extra or {})}
    return o.proponer(agente, "propuesta_cambio", titulo, cap, club_id, inst_id, prop, texto)


def _pendientes_de(agente, accion):
    res = o.db().table("cola_revision").select("id,propuesta").eq("agente", agente).in_("estado", ["pendiente", "bloqueada_legal"]).execute()
    return [r for r in (res.data or []) if (r.get("propuesta") or {}).get("accion") == accion]


# ---------------------------------------------------------------- Analista RSE (marketing/patrocinio)
RUBROS = [("traslado", r"\b(viaje|traslado|pasajes?|gira|micro|combustible)\b"),
          ("equipamiento", r"\b(sillas?|cubiertas?|repuestos?|tubulares?|equipamiento)\b"),
          ("indumentaria", r"\b(camisetas?|indumentaria|uniformes?)\b")]


def analista_rse(hoy=None):
    hoy = hoy or date.today()
    desde = (hoy - timedelta(days=60)).isoformat()
    nov = o.db().table("novedades_redes").select("id,club_id,url_publicacion,fecha_posteo,extracto") \
        .eq("publicado", True).eq("menciona_colecta", True).gte("fecha_posteo", desde).execute().data or []
    abiertos = o.db().table("pliegos_rse").select("club_id,rubro,estado").execute().data or []
    nombres = {c["id"]: c["nombre"] for c in (o.db().table("clubes").select("id,nombre").execute().data or [])}
    salida = []
    for n in nov:
        if not n.get("club_id"):
            continue
        t = o._norm(n.get("extracto", ""))
        rubro = next((r for r, rx in RUBROS if re.search(rx, t)), "a_definir")
        if any(p["club_id"] == n["club_id"] and p["rubro"] == rubro and p["estado"] in ("abierto", "empresa_postulada")
               for p in abiertos):
            continue
        club = nombres.get(n["club_id"], "el club")
        desc = (f"El club publicó que busca fondos ({rubro}). Propuesta: armar un pliego para que una empresa "
                f"pague directo al proveedor. Antes de publicar, hablar con el club y pedir 3 cotizaciones.")
        salida.append(proponer_cambio("analista_rse", f"Posible pliego RSE de {rubro} para {club}", n["url_publicacion"],
                                      "borrador_pliego_rse",
                                      {"rubro": rubro, "titulo": f"{rubro.capitalize()} para {club}", "descripcion": desc},
                                      club_id=n["club_id"], texto=n.get("extracto", ""),
                                      clave_unica=f"rse:{n['club_id']}:{rubro}"))
    return salida


# ---------------------------------------------------------------- Seguimiento de pedidos (jurídico-administrativo)
def borrador_reclamo(p):
    base = (f"Asunto: reclamo por falta de respuesta a pedido de acceso a la información pública\n\n"
            f"El {p['fecha_envio']} presenté ante {p['organismo']} un pedido de información sobre: {p['asunto']}. "
            f"El plazo para responder venció el {p['fecha_limite']} y no recibí respuesta. "
            f"Solicito que se responda el pedido o que se informen por escrito los motivos de la demora.")
    if p.get("ambito") == "nacional":
        base += ("\n\nNota interna: en el ámbito nacional rige la Ley 27.275; ante el incumplimiento corresponde un "
                 "reclamo ante la Agencia de Acceso a la Información Pública. Verificar plazos vigentes antes de enviar.")
    else:
        base += ("\n\nNota interna: verificar la norma de acceso a la información de la provincia o el municipio "
                 "y el organismo ante el que se reclama.")
    return base


def seguimiento_pedidos():
    vencidos = o.db().table("v_pedidos_vencidos").select("*").execute().data or []
    salida = []
    for p in vencidos:
        salida.append(proponer_cambio("seguimiento_pedidos", f"Reclamar pedido vencido: {p['organismo']} ({p['dias_de_atraso']} días)",
                                      f"{SITIO}#pedido-{p['id']}", "reclamar_pedido", {"pedido_id": p["id"]},
                                      club_id=p.get("club_id"), inst_id=p.get("institucion_id"),
                                      extra={"borrador_texto": borrador_reclamo(p)},
                                      clave_unica=f"reclamo:{p['id']}"))
    return salida


# ---------------------------------------------------------------- Control de vigencia
def _tokens_nombre(nombre):
    return [t for t in re.findall(r"[a-z]{3,}", o._norm(nombre))]


def control_vigencia():
    auts = o.db().table("autoridades").select("id,nombre,cargo,fuente_url,fecha_fuente,club_id,institucion_id") \
        .eq("publicable", True).eq("vigente", True).execute().data or []
    salida, por_fuente = [], {}
    for a in auts:
        if a.get("fuente_url"):
            por_fuente.setdefault(a["fuente_url"], []).append(a)
    for url, grupo in por_fuente.items():
        cap = o.capturar(url)
        time.sleep(o.PAUSA_SEG)
        if not cap.utilizable:
            continue
        texto = o._norm(o.texto_html(cap.contenido) if cap.contenido[:5] != b"%PDF-" else (o.texto_pdf(cap.contenido) or ""))
        if len(texto) < 500:            # página armada con JavaScript o sin texto: no se infiere nada
            continue
        for a in grupo:
            tok = _tokens_nombre(a["nombre"])
            if tok and not all(t in texto for t in tok):
                salida.append(proponer_cambio(
                    "control_vigencia", f"Revisar vigencia: {a['cargo']} ya no figura en la fuente", url,
                    "marcar_no_vigente", {"autoridad_id": a["id"]}, club_id=a.get("club_id"), inst_id=a.get("institucion_id"),
                    extra={"detalle": f"Se buscó el nombre publicado en la página oficial capturada hoy (hash {cap.sha256[:12]}…) "
                                      f"y no aparece. Puede ser un cambio de autoridades o un cambio en la página: verificar."},
                    clave_unica=f"vigencia:{a['id']}:{date.today():%Y-%m}"))   # como mucho un aviso por mes y persona
    # Datos de más de un año: UN aviso por tipo y por mes, con la lista adentro (no uno por persona).
    por_tipo = {}
    for h in o.db().table("v_hechos_vencidos").select("*").execute().data or []:
        por_tipo.setdefault(h["tipo"], []).append(h)
    mes = f"{date.today():%Y-%m}"
    for tipo, hs in por_tipo.items():
        hs.sort(key=lambda h: h.get("dias") or 0, reverse=True)
        salida.append(proponer_cambio("control_vigencia", f"{len(hs)} dato(s) de {tipo} con más de un año: volver a verificar",
                                      f"{SITIO}#vencidos-{tipo}-{mes}", "solo_informativa",
                                      {"tipo": tipo, "refs": [h["ref"] for h in hs]},
                                      extra={"detalle": "; ".join(f"{h['detalle']} (dato del {h['fecha_dato']}, {h['dias']} días)"
                                                                  for h in hs[:40])},
                                      clave_unica=f"vencidos:{tipo}:{mes}"))
    return salida


# ---------------------------------------------------------------- Delegado de protección de datos
def delegado_datos(hoy=None):
    hoy = hoy or date.today()
    if _pendientes_de("delegado_datos", "purgar_contactos"):
        return []
    limite = (hoy - timedelta(days=RETENCION_DIAS)).isoformat()
    n = 0
    for tabla, estados, col_vacia in (("tips", ["verificado", "descartado"], None),
                                      ("presentaciones_club", ["aprobada", "rechazada"], "(eliminado por retención)"),
                                      ("postulaciones_rse", ["descartada"], "(eliminado por retención)")):
        filas = o.db().table(tabla).select("id,contacto").in_("estado", estados).lt("creado_en", limite).execute().data or []
        n += sum(1 for f in filas if f.get("contacto") and f.get("contacto") != col_vacia)
    if not n:
        return []
    semana = hoy.isocalendar()
    return [proponer_cambio("delegado_datos", f"Borrar {n} contacto(s) de casos cerrados hace más de {RETENCION_DIAS} días",
                            f"{SITIO}#privacidad", "purgar_contactos", {"dias": RETENCION_DIAS},
                            extra={"detalle": "Minimización de datos (Ley 25.326): no se guarda un contacto más tiempo del necesario."},
                            clave_unica=f"purga:{semana[0]}-{semana[1]}")]


# ---------------------------------------------------------------- Analista de cruces
def analista_cruces():
    salida = []
    for c in o.db().table("v_cruces_expediente").select("*").execute().data or []:
        urls = sorted(c.get("urls") or [])
        if not urls:
            continue
        salida.append(proponer_cambio("analista_cruces", f"El expediente {c['expediente']} aparece en {c['fuentes']} fuentes",
                                      urls[0], "solo_informativa", {"expediente": c["expediente"]},
                                      extra={"detalle": "Fuentes: " + " · ".join(urls)},
                                      clave_unica=f"cruce:{c['expediente']}:{'|'.join(urls)}"))
    return salida


# ---------------------------------------------------------------- Guardián de seguridad (developer / DevOps)
def _rol_jwt(token):
    try:
        carga = token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        return json.loads(base64.urlsafe_b64decode(carga)).get("role")
    except Exception:
        return None


def secretos_en_texto(texto):
    """Devuelve descripciones (sin la clave) de claves secretas encontradas."""
    hallados = []
    for m in RE_JWT.finditer(texto or ""):
        if _rol_jwt(m.group(0)) == "service_role":
            hallados.append("clave service_role (JWT)")
    if RE_SB_SECRET.search(texto or ""):
        hallados.append("clave secreta sb_secret_")
    return hallados


def escanear_repo(raiz):
    hallazgos = []
    for p in Path(raiz).rglob("*"):
        if not p.is_file() or ".git" in p.parts or p.suffix.lower() not in (".py", ".yml", ".yaml", ".html", ".js", ".json", ".md", ".txt", ".toml", ".env"):
            continue
        try:
            txt = p.read_text("utf-8", "ignore")
        except Exception:
            continue
        for i, linea in enumerate(txt.splitlines(), 1):
            for h in secretos_en_texto(linea):
                hallazgos.append(f"{p.relative_to(raiz)}:{i} — {h}")
    return hallazgos


def _get(url, cabeceras=None, metodo="GET", cuerpo=None):
    req = urllib.request.Request(url, data=cuerpo, method=metodo, headers={"User-Agent": o.UA, **(cabeceras or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.getcode(), {k.lower(): v for k, v in r.headers.items()}, r.read(o.MAX_BYTES)
    except urllib.error.HTTPError as e:
        return e.code, {}, b""
    except Exception:
        return 0, {}, b""


def sondeo_rls(url_supabase, clave_publica):
    """Con la clave PÚBLICA, ninguna tabla privada debe devolver filas y el panel no debe responder."""
    expuestas = []
    h = {"apikey": clave_publica}
    if clave_publica.startswith("eyJ"):
        h["Authorization"] = f"Bearer {clave_publica}"
    for t in TABLAS_PRIVADAS:
        code, _, body = _get(f"{url_supabase.rstrip('/')}/rest/v1/{t}?select=*&limit=1", h)
        if code == 200 and body.strip() not in (b"", b"[]"):
            expuestas.append(t)
    code, _, _ = _get(f"{url_supabase.rstrip('/')}/rest/v1/rpc/panel_bandeja", {**h, "Content-Type": "application/json"}, "POST", b"{}")
    if 200 <= code < 300:
        expuestas.append("rpc panel_bandeja")
    return expuestas


def guardian_seguridad(raiz_repo=None, url_supabase=None, clave_publica=None):
    """Devuelve (resultados, hay_critico)."""
    salida, critico = [], False
    raiz_repo = raiz_repo or os.environ.get("GITHUB_WORKSPACE")
    if raiz_repo:
        h = escanear_repo(raiz_repo)
        if h:
            critico = True
            salida.append(proponer_cambio("guardian_seguridad", f"CRÍTICO: {len(h)} clave(s) secreta(s) en el repositorio público",
                                          REPO, "solo_informativa", {"archivos": h[:20]},
                                          extra={"detalle": "Rotar la clave en Supabase (Settings → API Keys), moverla a GitHub Secrets "
                                                            "y borrar el archivo. Ubicación: " + "; ".join(h[:20])},
                                          clave_unica="repo:" + "|".join(h)))
    code, cab, body = _get(SITIO)
    if code == 200:
        s = secretos_en_texto(body.decode("utf-8", "ignore"))
        if s:
            critico = True
            salida.append(proponer_cambio("guardian_seguridad", "CRÍTICO: el sitio publica una clave secreta", SITIO,
                                          "solo_informativa", {"hallazgos": s},
                                          extra={"detalle": "En el sitio solo puede ir la clave publicable/anon. Rotar la secreta ya."},
                                          clave_unica="sitio:" + hashlib.sha256(body).hexdigest()))
        faltan = [c for c in CABECERAS if c not in cab
                  and not (c == "content-security-policy" and "content-security-policy-report-only" in cab)]
        if faltan:
            salida.append(proponer_cambio("guardian_seguridad", "Faltan cabeceras de seguridad en el sitio", SITIO,
                                          "solo_informativa", {"faltan": faltan},
                                          extra={"detalle": "Se agregan con un archivo _headers al publicar en Cloudflare: " + ", ".join(faltan)},
                                          clave_unica="cabeceras:" + ",".join(faltan)))
    url_supabase = url_supabase or os.environ.get("SUPABASE_URL")
    clave_publica = clave_publica or os.environ.get("SUPABASE_ANON_KEY")
    if url_supabase and clave_publica:
        exp = sondeo_rls(url_supabase, clave_publica)
        if exp:
            critico = True
            salida.append(proponer_cambio("guardian_seguridad", "CRÍTICO: datos privados legibles con la clave pública",
                                          url_supabase.rstrip("/") + "/", "solo_informativa", {"expuestas": exp},
                                          extra={"detalle": "Revisar RLS y permisos (db/02 y db/09) de: " + ", ".join(exp)},
                                          clave_unica="rls:" + ",".join(exp)))
    return salida, critico


ESPECIALISTAS = [analista_rse, seguimiento_pedidos, control_vigencia, delegado_datos, analista_cruces]


def main():
    ej = o.db().table("agente_ejecuciones").insert({"agente": "especialistas", "objetivos": len(ESPECIALISTAS) + 1}).execute()
    ej_id = ej.data[0]["id"] if ej.data else None
    resumen, errores = {}, 0
    for f in ESPECIALISTAS:
        try:
            r = f()
            resumen[f.__name__] = {"nuevas": r.count("nuevo"), "bloqueadas": r.count("bloqueado_legal"), "repetidas": r.count("duplicado")}
        except Exception as e:                       # un especialista que falla no frena a los demás
            errores += 1
            resumen[f.__name__] = {"error": str(e)[:200]}
    try:
        r, critico = guardian_seguridad()
        resumen["guardian_seguridad"] = {"nuevas": r.count("nuevo"), "critico": critico}
    except Exception as e:
        errores += 1
        critico = False
        resumen["guardian_seguridad"] = {"error": str(e)[:200]}
    if ej_id:
        o.db().table("agente_ejecuciones").update({"fin": o.ahora().isoformat(), "ok": len(resumen) - errores,
                                                   "errores": errores, "detalle": resumen}).eq("id", ej_id).execute()
    print(json.dumps(resumen, ensure_ascii=False))
    if critico:
        print("HALLAZGO CRÍTICO DE SEGURIDAD: revisar el panel (Bandeja) ahora.")
        sys.exit(2)


if __name__ == "__main__":
    main()
