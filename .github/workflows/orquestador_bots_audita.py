"""AuditaDeporte - orquestador v2.1
Registra documentos oficiales como BORRADOR (publicado=false) con el SHA-256 real del archivo.
Una persona escribe el resumen y publica desde Supabase (ver db/05_*.sql).
El bot NO escribe 'no_encontrado' ni pisa revisiones hechas por personas.
Secrets en GitHub Actions: SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY (nunca en el sitio ni en el repo)."""
import os
import hashlib
import urllib.request
from typing import Optional

_cliente = None


def db():
    """Cliente Supabase con service role, creado recién al usarse."""
    global _cliente
    if _cliente is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY.")
        _cliente = create_client(url, key)
    return _cliente


def sha256_desde_url(url: str) -> Optional[str]:
    """SHA-256 de los bytes realmente descargados. Si la descarga falla devuelve None (no se inventa un hash)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AuditaDeporteBot/2.1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return hashlib.sha256(r.read()).hexdigest()
    except Exception as exc:
        print(f"[WARN] No se pudo descargar {url}: {exc}")
        return None


def mapa_slugs(tabla: str) -> dict:
    res = db().table(tabla).select("id, slug").execute()
    return {f["slug"]: f["id"] for f in (res.data or [])}


def registrar_documento_fuente(club_slug=None, institucion_slug=None, portal_origen="sitio_oficial",
                               titulo="", expediente_o_norma="", url_fuente="", clubes_map=None, inst_map=None):
    club_id = (clubes_map or {}).get(club_slug) if club_slug else None
    inst_id = (inst_map or {}).get(institucion_slug) if institucion_slug else None
    if (club_id is None) == (inst_id is None):
        print(f"[SKIP] Destino no encontrado para '{titulo}' (club={club_slug}, inst={institucion_slug})")
        return False
    h = sha256_desde_url(url_fuente)
    if not h:
        print(f"[SKIP] Sin descarga no se registra: {titulo}")
        return False
    ya = db().table("documentos_fuente").select("id").eq("url_fuente", url_fuente).eq("hash_sha256", h).execute()
    if ya.data:
        print(f"[OK] Sin cambios: {titulo}")
        return False
    db().table("documentos_fuente").insert({
        "club_id": club_id, "institucion_id": inst_id, "portal_origen": portal_origen, "titulo": titulo,
        "expediente_o_norma": expediente_o_norma or None, "url_fuente": url_fuente, "hash_sha256": h,
        "publicado": False,  # borrador: falta resumen humano
    }).execute()
    print(f"[INSERT borrador] {titulo} ({h[:12]}...)")
    return True


def ejecutar_ciclo_auditoria():
    clubes, insts = mapa_slugs("clubes"), mapa_slugs("instituciones")
    print(f"Clubes: {len(clubes)} | Instituciones: {len(insts)}")
    for titulo, url in [
        ("Boletín Oficial Alte. Brown - Enero 2026 (decretos)", "https://files.brown.gob.ar/brown-web/bundles/site/pdf/boletin_oficial/PQ-Enero-Decretos-2026.pdf"),
        ("Ficha del club en el padrón web de FABA - Alte. Brown", "https://basquetadaptado.com.ar/clubes/instituto-municipal-del-deporte-almirante-brown/"),
    ]:
        registrar_documento_fuente(club_slug="brown",
            portal_origen="boletin_municipal" if "brown.gob.ar" in url else "sitio_oficial",
            titulo=titulo, url_fuente=url, clubes_map=clubes, inst_map=insts)
    registrar_documento_fuente(institucion_slug="faba", titulo="Autoridades FABA (web oficial)",
        url_fuente="https://basquetadaptado.com.ar/autoridades/", clubes_map=clubes, inst_map=insts)
    registrar_documento_fuente(institucion_slug="copar", titulo="Autoridades COPAR (web oficial)",
        url_fuente="https://www.coparg.org.ar/nosotros/", clubes_map=clubes, inst_map=insts)
    print("Ciclo terminado. Los documentos nuevos quedan como borrador hasta que una persona los resuma y publique.")


if __name__ == "__main__":
    ejecutar_ciclo_auditoria()
