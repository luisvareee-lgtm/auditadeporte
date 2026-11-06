"""Solo lectura: lista columnas de tablas clave y funciones RPC que la base expone (vía OpenAPI de PostgREST)."""
import json, os, urllib.request
url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
k = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": k, "Accept": "application/openapi+json"}
if k.startswith("eyJ"): h["Authorization"] = "Bearer " + k
api = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30))
defs = api.get("definitions", {})
for t in ("tips", "documentos_cargados", "documentos_fuente", "pedidos_presentados", "pliegos_rse", "presentaciones_club"):
    print(t, "->", sorted((defs.get(t) or {}).get("properties", {}).keys()) or "NO EXISTE")
rpcs = sorted(p.split("/rpc/")[1] for p in api.get("paths", {}) if "/rpc/" in p)
for f in ("panel_bandeja", "panel_documentos_cargados", "panel_cargar_documento", "panel_capturas_documento", "panel_tip_a_pliego",
          "contar_pedidos_presentados", "panel_detalle"):
    print(f, "OK" if f in rpcs else "FALTA")
