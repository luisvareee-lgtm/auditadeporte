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
