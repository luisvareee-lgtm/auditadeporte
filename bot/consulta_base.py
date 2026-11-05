"""Consulta de solo lectura para diagnóstico: clubes con ciudad/provincia/tipo y fuentes ya cargadas. No escribe nada."""
import orquestador_bots_audita as o
cl = o.db().table("clubes").select("id,slug,nombre,tipo_entidad,ciudad,provincia,publicado,estado_afiliacion,web").execute().data or []
fu = o.db().table("fuentes_monitoreadas").select("club_id,institucion_id,nombre,url,tipo,estado").execute().data or []
ins = o.db().table("instituciones").select("id,slug,nombre,ambito").execute().data or []
print("CLUBES")
for c in sorted(cl, key=lambda x: (x["provincia"], x["ciudad"])):
    n = sum(1 for f in fu if f.get("club_id") == c["id"])
    print(f"{c['slug']}|{c['nombre']}|{c['tipo_entidad']}|{c['ciudad']}|{c['provincia']}|pub={c['publicado']}|{c['estado_afiliacion']}|fuentes={n}|web={c.get('web')}")
print("INSTITUCIONES")
for i in ins:
    print(f"{i['slug']}|{i['nombre']}|{i['ambito']}|fuentes={sum(1 for f in fu if f.get('institucion_id') == i['id'])}")
print("FUENTES")
for f in fu:
    print(f"{f['tipo']}|{f['estado']}|{f['url']}")
print("ESTADO FUENTES")
for f in o.db().table("fuentes_monitoreadas").select("nombre,url,estado,ultimo_status,fallos_consecutivos").execute().data or []:
    if f.get("ultimo_status") != 200 or f.get("estado") != "activa":
        print(f"{f['estado']}|{f.get('ultimo_status')}|fallos={f.get('fallos_consecutivos')}|{f['nombre']}")
print("COLA PENDIENTE POR AGENTE Y TIPO")
cola = o.db().table("cola_revision").select("agente,tipo,estado,titulo").eq("estado", "pendiente").execute().data or []
conteo = {}
for c in cola:
    conteo[(c["agente"], c["tipo"])] = conteo.get((c["agente"], c["tipo"]), 0) + 1
for (a, t), n in sorted(conteo.items()):
    print(f"{a}|{t}|{n}")
print("EJEMPLOS DEL ORQUESTADOR")
for c in [c for c in cola if c["agente"] not in ("relevador_faba", "actualidad_redes")][:25]:
    print(f"{c['agente']}|{c['tipo']}|{c['titulo'][:110]}")
