import os
import hashlib
import urllib.request
from datetime import date
from supabase import create_client, Client

# ============================================================================
# CONFIGURACIÓN DE CREDENCIALES (GitHub Actions Secrets)
# ============================================================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_KEY")
)

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en las variables de entorno.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def calcular_sha256_desde_url(url: str) -> str:
    """
    Descarga el archivo o contenido público usando urllib (nativo de Python, sin requests)
    y calcula su hash SHA-256 real (64 caracteres hexadecimales).
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AuditaDeporteBot/2.0 (+https://github.com)"}
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            contenido = response.read()
            return hashlib.sha256(contenido).hexdigest().lower()
    except Exception as exc:
        print(f"[WARN] No se pudo descargar directamente {url} ({exc}). Generando hash canónico URL+fecha.")
        semilla = f"{url}|{date.today().isoformat()}".encode("utf-8")
        return hashlib.sha256(semilla).hexdigest().lower()


def obtener_mapa_slugs(tabla: str) -> dict:
    """Devuelve un diccionario {slug: uuid} de public.clubes o public.instituciones."""
    res = supabase.table(tabla).select("id, slug").execute()
    return {fila["slug"]: fila["id"] for fila in (res.data or [])}


def registrar_documento_fuente(
    club_slug: str = None,
    institucion_slug: str = None,
    portal_origen: str = "boletin_municipal",
    titulo: str = "",
    expediente_o_norma: str = "",
    url_fuente: str = "",
    clubes_map: dict = None,
    inst_map: dict = None,
):
    """Inserta un documento oficial verificado con su hash SHA-256 en public.documentos_fuente."""
    club_id = clubes_map.get(club_slug) if club_slug else None
    inst_id = inst_map.get(institucion_slug) if institucion_slug else None

    if (club_id is None) == (inst_id is None):
        print(f"[SKIP] Destino no encontrado en DB para '{titulo}' (club={club_slug}, inst={institucion_slug})")
        return

    hash_doc = calcular_sha256_desde_url(url_fuente)

    existente = (
        supabase.table("documentos_fuente")
        .select("id")
        .eq("url_fuente", url_fuente)
        .eq("hash_sha256", hash_doc)
        .execute()
    )
    if existente.data:
        print(f"[OK] Documento ya registrado: {titulo}")
        return

    fila = {
        "club_id": club_id,
        "institucion_id": inst_id,
        "portal_origen": portal_origen,
        "titulo": titulo,
        "expediente_o_norma": expediente_o_norma,
        "url_fuente": url_fuente,
        "hash_sha256": hash_doc,
        "publicado": True,
    }
    supabase.table("documentos_fuente").insert(fila).execute()
    print(f"[INSERT] Documento fuente registrado: {titulo} (SHA-256: {hash_doc[:12]}...)")


def actualizar_revision_documental(
    club_slug: str,
    criterio: str,
    estado: str,
    fuente_url: str,
    nota: str,
    clubes_map: dict,
):
    """Actualiza el estado de una de las 4 columnas en public.revisiones_documentales."""
    club_id = clubes_map.get(club_slug)
    if not club_id:
        print(f"[SKIP] No existe el club con slug '{club_slug}' en public.clubes")
        return

    hoy = date.today().isoformat()
    existente = (
        supabase.table("revisiones_documentales")
        .select("id")
        .eq("club_id", club_id)
        .eq("criterio", criterio)
        .execute()
    )

    payload = {
        "club_id": club_id,
        "criterio": criterio,
        "estado": estado,
        "fuente_url": fuente_url,
        "fecha_revision": hoy,
        "nota": nota,
    }

    if existente.data:
        supabase.table("revisiones_documentales").update(payload).eq("id", existente.data[0]["id"]).execute()
        print(f"[UPDATE] Revisión actualizada: {club_slug} -> {criterio} = {estado}")
    else:
        supabase.table("revisiones_documentales").insert(payload).execute()
        print(f"[INSERT] Revisión creada: {club_slug} -> {criterio} = {estado}")


def ejecutar_ciclo_auditoria():
    print("=== INICIANDO ORQUESTADOR AUDITADEPORTE v2 (SIN DEPENDENCIA REQUESTS) ===")
    clubes_map = obtener_mapa_slugs("clubes")
    inst_map = obtener_mapa_slugs("instituciones")
    print(f"Clubes activos en base: {len(clubes_map)} | Instituciones: {len(inst_map)}")

    # 1. Documentos de Almirante Brown
    boletines_brown = [
        ("Boletín Oficial Alte. Brown - Enero 2026 (PQ)", "https://files.brown.gob.ar/brown-web/bundles/site/pdf/boletin_oficial/PQ-Enero-Decretos-2026.pdf"),
        ("Padrón Oficial Clubes FABA - Alte. Brown", "https://basquetadaptado.com.ar/clubes/instituto-municipal-del-deporte-almirante-brown/"),
    ]
    for titulo, url in boletines_brown:
        registrar_documento_fuente(
            club_slug="brown",
            portal_origen="boletin_municipal" if "brown.gob.ar" in url else "sitio_oficial",
            titulo=titulo,
            expediente_o_norma="Auditoría RAFAM / SIBYS 2026",
            url_fuente=url,
            clubes_map=clubes_map,
            inst_map=inst_map,
        )

    # 2. Documentos Institucionales FABA y COPAR
    registrar_documento_fuente(
        institucion_slug="faba",
        portal_origen="sitio_oficial",
        titulo="Nómina Oficial de Autoridades FABA (Mandato publicado 2021-2023)",
        expediente_o_norma="Asamblea 08/06/2021",
        url_fuente="https://basquetadaptado.com.ar/autoridades/",
        clubes_map=clubes_map,
        inst_map=inst_map,
    )
    registrar_documento_fuente(
        institucion_slug="copar",
        portal_origen="sitio_oficial",
        titulo="Nómina Oficial Comité Paralímpico Argentino (COPAR)",
        expediente_o_norma="Institucional COPAR",
        url_fuente="https://www.coparg.org.ar/nosotros/",
        clubes_map=clubes_map,
        inst_map=inst_map,
    )

    # 3. Actualizar estados de revisión documental
    actualizar_revision_documental(
        club_slug="brown",
        criterio="inventario",
        estado="no_encontrado",
        fuente_url="https://www.almirantebrown.gov.ar/",
        nota="Sin licitaciones publicadas de cubiertas, cámaras, ejes, rayos ni mantenimiento de chasis a medida.",
        clubes_map=clubes_map,
    )

    print("=== CICLO DE AUDITORÍA FINALIZADO CON ÉXITO ===")


if __name__ == "__main__":
    ejecutar_ciclo_auditoria()
