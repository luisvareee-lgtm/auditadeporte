"""Prueba integral (no deja rastros): revisa que todo el circuito funcione de punta a punta.

1. Base de datos: que existan las tablas y funciones de cada SQL (15 a 24) y cuántos datos tienen.
2. Formularios públicos del sitio, como si fuera un visitante (con la clave pública): sumar un pedido presentado,
   cargar una convocatoria, mandar una solicitud de patrocinio, leer los contadores. Cada fila de prueba se borra
   al final. Además controla que un visitante NO pueda leer los mensajes privados.
3. Meta (Instagram): qué permisos tiene el token, cuándo vence, si lee la cuenta propia y qué responde Meta
   al pedir otra cuenta (FABA). Así se ve exactamente qué falta del permiso.
Uso: python prueba_integral.py   (secrets: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, META_TOKEN, IG_USER_ID)
"""
import json
import os
import re
import urllib.parse
import urllib.request

from supa import Cliente, SupaError

AQUI = os.path.dirname(os.path.abspath(__file__))
RES = []


def nota(estado, que, detalle=""):
    RES.append((estado, que, detalle))
    print(f"[{estado}] {que}" + (f" — {detalle}" if detalle else ""), flush=True)


def clave_publica():
    html = open(os.path.join(AQUI, "..", "index.html"), encoding="utf-8").read()
    return re.search(r'SUPABASE_ANON_KEY:\s*"([^"]+)"', html).group(1)


TABLAS = [("15", "pedidos_presentados"), ("16", "documentos_cargados"), ("18", "alertas_vigia"), ("20", "ejecuciones_presupuestarias"),
          ("21", "colectas_relevadas"), ("23", "convocatorias"), ("24", "barrido_redes"), ("24", "publicaciones_relevantes")]
COLUMNAS = [("22", "colectas_relevadas", "tipos_pedido,destinatarios,fecha_limite,fuente,revisada")]


def base(srv):
    print("\n== 1. Base de datos ==")
    for sql, t in TABLAS:
        try:
            n = len(srv.table(t).select("*").limit(1000).execute().data or [])
            nota("OK", f"tabla {t} (db/{sql})", f"{n}{'+' if n == 1000 else ''} fila(s)")
        except SupaError as e:
            nota("FALTA", f"tabla {t}", f"correr db/{sql} ({str(e)[:80]})")
    for sql, t, cols in COLUMNAS:
        try:
            srv.table(t).select(cols).limit(1).execute()
            nota("OK", f"columnas nuevas de {t} (db/{sql})")
        except SupaError as e:
            nota("FALTA", f"columnas nuevas de {t}", f"correr db/{sql}")


def publico(srv, anon):
    print("\n== 2. Formularios públicos (como visitante) ==")
    # a) contador "ya lo presenté"
    try:
        anon.table("pedidos_presentados").insert([{"juris_slug": "muni-prueba-automatica"}], minimal=True).execute()
        n = [r for r in anon.rpc("contar_pedidos_presentados").execute().data or [] if r["juris_slug"] == "muni-prueba-automatica"]
        nota("OK" if n else "FALLA", "sumar un pedido presentado y verlo en el contador")
    except SupaError as e:
        nota("FALLA", "sumar un pedido presentado", str(e)[:120])
    finally:
        _borrar(srv, "pedidos_presentados", "juris_slug", "muni-prueba-automatica")
    # b) convocatoria a torneo
    try:
        anon.table("convocatorias").insert([{"club_id": "prueba-automatica", "fecha_aviso": "2025-07-01", "fecha_torneo": "2025-08-01",
                                             "cambio_fecha": True, "canal": "whatsapp", "cobertura": "parcial", "viajaron": "parte"}], minimal=True).execute()
        r = anon.rpc("resumen_convocatorias").execute().data or {}
        ok = any(g.get("club_id") == "prueba-automatica" and g.get("prom") == 31 for g in r.get("por_club") or [])
        nota("OK" if ok else "FALLA", "cargar una convocatoria y verla en el promedio", "31 días de anticipación calculados" if ok else json.dumps(r)[:120])
    except SupaError as e:
        nota("FALLA", "cargar una convocatoria", str(e)[:120])
    finally:
        _borrar(srv, "convocatorias", "club_id", "prueba-automatica")
    # c) solicitud de patrocinio (llega a la Bandeja del panel)
    texto = "[PRUEBA AUTOMÁTICA, se borra sola] Necesitamos repuestos de silla para el torneo nacional del club."
    try:
        anon.table("tips").insert([{"tipo": "solicitud_rse", "club_id": None, "texto": texto, "url": None, "contacto": "prueba"}], minimal=True).execute()
        llego = srv.table("tips").select("id,estado").eq("texto", texto).execute().data
        nota("OK" if llego else "FALLA", "mandar una solicitud de patrocinio y que llegue a la Bandeja", f"estado: {llego[0]['estado']}" if llego else "")
    except SupaError as e:
        nota("FALLA", "mandar una solicitud de patrocinio", str(e)[:120])
    finally:
        _borrar(srv, "tips", "texto", texto)
    # d) privacidad: un visitante no puede leer mensajes ni colectas sin revisar
    for t in ("tips", "colectas_relevadas", "convocatorias", "publicaciones_relevantes"):
        try:
            filas = anon.table(t).select("*").limit(1).execute().data or []
            nota("OK" if not filas else "FALLA", f"un visitante no puede leer {t}", "" if not filas else "¡se ven filas!")
        except SupaError:
            nota("OK", f"un visitante no puede leer {t}")


def _borrar(srv, tabla, col, valor):
    try:
        srv.table(tabla).delete().eq(col, valor).execute()
    except SupaError as e:
        nota("AVISO", f"no se pudo borrar la prueba de {tabla}", str(e)[:80])


def _graph(ruta, params):
    q = urllib.parse.urlencode({**params, "access_token": os.environ["META_TOKEN"]})
    try:
        with urllib.request.urlopen(f"https://graph.facebook.com/v27.0/{ruta}?{q}", timeout=30) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except Exception:
            err = {}
        return None, err


def meta():
    print("\n== 3. Meta (Instagram) ==")
    if not os.environ.get("META_TOKEN"):
        nota("FALTA", "secret META_TOKEN"); return
    tok = os.environ["META_TOKEN"]
    d, err = _graph("debug_token", {"input_token": tok})
    if d:
        info = d.get("data") or {}
        vence = info.get("expires_at") or 0
        nota("OK" if info.get("is_valid") else "FALLA", "token de Meta válido",
             f"tipo {info.get('type')}, vence {'nunca' if not vence else __import__('datetime').datetime.utcfromtimestamp(vence).date()}")
        alcances = set(info.get("scopes") or [])
        for p in ("instagram_basic", "instagram_manage_insights", "pages_read_engagement", "pages_show_list", "business_management"):
            nota("OK" if p in alcances else "AVISO", f"permiso {p} en el token", "" if p in alcances else "no está en el token")
        print("  todos los permisos del token:", ", ".join(sorted(alcances)), "| app:", info.get("application"), info.get("app_id"))
    else:
        nota("FALLA", "token de Meta", (err or {}).get("message", "")[:120])
    ig = os.environ.get("IG_USER_ID", "")
    d, err = _graph(ig, {"fields": "username,media_count"})
    if d:
        nota("OK", "leer la cuenta propia", f"@{d.get('username')}, {d.get('media_count')} posteos")
        propia = d.get("username")
        d2, err2 = _graph(ig, {"fields": f"business_discovery.username({propia}){{username,media_count}}"})
        nota("OK" if d2 else "FALLA", "Business Discovery sobre la cuenta propia",
             "la consulta de otras cuentas funciona" if d2 else (err2 or {}).get("message", "")[:140])
    else:
        nota("FALLA", "leer la cuenta propia", (err or {}).get("message", "")[:120])
    for otra in ("basquetadaptadofaba", "comiteparalimpicoargentino"):
        d, err = _graph(ig, {"fields": f"business_discovery.username({otra}){{username,media_count}}"})
        if d:
            bd = d.get("business_discovery") or {}
            nota("OK", f"leer @{otra}", f"{bd.get('media_count')} posteos disponibles para barrer")
        else:
            nota("BLOQUEADO", f"leer @{otra}", f"código {err.get('code')}: {err.get('message', '')[:140]}")


def main():
    srv = Cliente(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    anon = Cliente(os.environ.get("SUPABASE_URL"), clave_publica())
    base(srv)
    publico(srv, anon)
    meta()
    print("\n== Resumen ==")
    for e in ("OK", "AVISO", "BLOQUEADO", "FALTA", "FALLA"):
        print(f"{e}: {sum(1 for r in RES if r[0] == e)}")


if __name__ == "__main__":
    main()
