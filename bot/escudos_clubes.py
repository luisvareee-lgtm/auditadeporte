"""Propone el escudo de cada club tomando la foto de perfil de su cuenta oficial pública de Instagram (Business
Discovery, la vía autorizada de Meta). No publica nada: lo deja en escudos_propuestos y una persona lo aprueba en el
panel (a veces la foto de perfil es una persona o un evento y no el escudo).
La imagen nunca se sirve desde Meta: se baja, se vuelve a codificar como .webp de 256 px (eso descarta metadatos y
cualquier cosa que no sea la imagen), se calcula su huella sha256 y se guarda en nuestro almacenamiento con la huella
en el nombre, así el archivo publicado no puede cambiar sin que cambie su dirección.
Uso: python escudos_clubes.py [--todos]   (--todos vuelve a proponer aunque el club ya tenga escudo)
"""
import hashlib
import io
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


LADO = 256


def normalizar_escudo(datos: bytes):
    """(bytes .webp cuadrado de 256 px con fondo transparente, sha256 en hexadecimal). Falla si no es una imagen."""
    from PIL import Image
    Image.open(io.BytesIO(datos)).verify()                     # corta si el archivo está roto o no es imagen
    im = Image.open(io.BytesIO(datos))
    if im.width * im.height > 40_000_000:
        raise ValueError("imagen demasiado grande")
    im = im.convert("RGBA")
    im.thumbnail((LADO, LADO))
    lienzo = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    lienzo.paste(im, ((LADO - im.width) // 2, (LADO - im.height) // 2), im)
    salida = io.BytesIO()
    lienzo.save(salida, "WEBP", quality=88, method=6)          # se escribe de cero: sin EXIF ni datos agregados
    webp = salida.getvalue()
    return webp, hashlib.sha256(webp).hexdigest()


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
            datos, _ = bajar_imagen(foto)
            webp, huella = normalizar_escudo(datos)
            ruta = f"escudos/{c['slug']}-{huella[:16]}.webp"
            cli.subir_archivo(BUCKET, ruta, webp, "image/webp")
            fila = {"club_id": c["id"], "url": base + ruta, "fuente": f"instagram:@{u}", "sha256": huella}
            try:
                cli.table("escudos_propuestos").upsert([fila], on_conflict="club_id").execute()
            except Exception:                                   # sin db/29 todavía no existe la columna de la huella
                fila.pop("sha256")
                cli.table("escudos_propuestos").upsert([fila], on_conflict="club_id").execute()
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
