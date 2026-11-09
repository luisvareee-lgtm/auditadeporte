"""Propone el escudo de cada club tomando la foto de perfil de su cuenta oficial pública de Instagram (Business
Discovery, la vía autorizada de Meta). No publica nada: lo deja en escudos_propuestos y una persona lo aprueba en el
panel (a veces la foto de perfil es una persona o un evento y no el escudo).
Uso: python escudos_clubes.py [--todos]   (--todos vuelve a proponer aunque el club ya tenga escudo)
"""
import os
import sys
import time
import urllib.request

import actualidad_redes as ar
import orquestador_bots_audita as o

BUCKET = "capturas-publicas"


def bajar_imagen(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AuditaDeporteBot/5.0 (observatorio civico)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        datos, tipo = r.read(2_000_000), r.headers.get("Content-Type", "")
    if not tipo.startswith("image/") or len(datos) < 500:
        raise ValueError(f"no es una imagen ({tipo})")
    return datos, ("image/png" if "png" in tipo else "image/jpeg")


def main():
    todos = "--todos" in sys.argv
    ig, propia = os.environ["IG_USER_ID"], None
    cli = o.db()
    clubes = cli.table("clubes").select("id,slug,nombre,instagram,logo_url").execute().data or []
    base = os.environ["SUPABASE_URL"].rstrip("/") + f"/storage/v1/object/public/{BUCKET}/"
    try:
        cli.table("escudos_propuestos").select("club_id").limit(1).execute()
        prueba = False
    except Exception:
        prueba = True
        print("Falta correr db/28: solo se informa qué cuentas tienen foto de perfil, sin subir nada.")
    for c in clubes:
        u = (c.get("instagram") or "").strip().lstrip("@")
        if not u or (c.get("logo_url") and not todos):
            continue
        try:
            d = ar.graph(ig, f"business_discovery.username({u}){{username,name,profile_picture_url}}").get("business_discovery") or {}
            foto = d.get("profile_picture_url")
            if not foto:
                print(f"{c['nombre']}: @{u} sin foto de perfil disponible"); continue
            if prueba:
                print(f"{c['nombre']}: @{u} tiene foto de perfil disponible"); continue
            datos, tipo = bajar_imagen(foto)
            ruta = f"escudos/propuestos/{c['slug']}-{int(time.time())}.{'png' if tipo == 'image/png' else 'jpg'}"
            cli.subir_archivo(BUCKET, ruta, datos, tipo)
            cli.table("escudos_propuestos").upsert([{"club_id": c["id"], "url": base + ruta, "fuente": f"instagram:@{u}"}],
                                                  on_conflict="club_id").execute()
            print(f"{c['nombre']}: escudo propuesto desde @{u}")
        except ar.ErrorMeta as e:
            print(f"{c['nombre']}: @{u} {e.estado}")
            if e.estado == "limite_meta":
                break
        except Exception as e:
            print(f"{c['nombre']}: @{u} no se pudo ({str(e)[:100]})")
        time.sleep(ar.PAUSA)


if __name__ == "__main__":
    main()
