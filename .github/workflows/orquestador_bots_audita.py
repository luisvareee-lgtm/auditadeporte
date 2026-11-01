import hashlib
import os
import re
import time
from datetime import datetime, timezone
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

UA = "AuditaDeporteBot/5.0 (observatorio civico sin fines de lucro; contacto en el sitio)"
PAUSA_SEG = 2.0           # cortesía entre pedidos al mismo sitio
_cliente = None


def db():
    global _cliente
    if _cliente is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY.")
        _cliente = create_client(url, key)
    return _cliente


# ---------------------------------------------------------------- Agente Rastreador
@dataclass
class Captura:
    url: str
    http: int                 # 0 = error de red; 401/403/429 = bloqueo (se respeta)
    contenido: bytes = b""
    sha256: Optional[str] = None
    motivo: str = ""

    @property
    def bloqueada(self):
        return self.http in (401, 403, 429)

    @property
    def utilizable(self):
        return self.http == 200 and bool(self.contenido)


def _robots_permite(url: str) -> bool:
    p = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch(UA, url)
    except Exception:
        return True  # si robots.txt no responde, seguimos con ritmo cortés


def capturar(url: str, timeout: int = 20) -> Captura:
    """Descarga honesta: se identifica, respeta robots.txt, no rota identidades ni reintenta bloqueos."""
    if not url.lower().startswith(("http://", "https://")):
        return Captura(url, 0, motivo="url_invalida")
    if not _robots_permite(url):
        return Captura(url, 0, motivo="robots_no_permite")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return Captura(url, r.getcode(), data, hashlib.sha256(data).hexdigest())
    except urllib.error.HTTPError as e:
        return Captura(url, e.code, motivo=f"http_{e.code}")
    except Exception as exc:
        return Captura(url, 0, motivo=f"red:{exc}")


# ---------------------------------------------------------------- Agente Jurídico (pre-filtro)
def _norm(t: str) -> str:
    return unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()


TERMINOS_VETADOS = ["corrupcion", "corrupto", "robo", "robaron", "estafa", "malversacion", "delito",
                    "fraude", "ilegal", "ladron", "coima", "desvio de fondos", "mafia"]
RE_DNI = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}\b")
RE_CUIL = re.compile(r"\b(20|23|24|27|30|33)-?\d{8}-?\d\b")


def pre_filtro_juridico(texto: str, url: str) -> list:
    """Devuelve motivos de bloqueo ([] = puede pasar a revisión humana).
    NO es una validación legal: solo evita que entren a la cola calificativos, imputaciones o datos personales."""
    motivos, t = [], _norm(texto or "")
    for term in TERMINOS_VETADOS:
        if re.search(rf"\b{re.escape(term)}\b", t):
            motivos.append(f"termino_vetado:{term}")
    if RE_DNI.search(texto or "") or RE_CUIL.search(texto or ""):
        motivos.append("posible_dato_personal(DNI/CUIL)")
    if not (url or "").lower().startswith(("http://", "https://")):
        motivos.append("sin_fuente_verificable")
    return motivos


# ---------------------------------------------------------------- Cola de revisión y registro
def mapa_slugs(tabla: str) -> dict:
    res = db().table(tabla).select("id, slug").execute()
    return {f["slug"]: f["id"] for f in (res.data or [])}


def proponer(agente, tipo, titulo, cap: Captura, club_id=None, inst_id=None, propuesta=None, texto_para_filtro=""):
    """Inserta en cola_revision (privada). Devuelve 'nuevo' | 'duplicado' | 'bloqueado_legal'."""
    previo = db().table("cola_revision").select("id") \
        .eq("url_fuente", cap.url).eq("hash_sha256", cap.sha256).execute()
    if previo.data:
        return "duplicado"
    veto = pre_filtro_juridico(f"{titulo} {texto_para_filtro}", cap.url)
    fila = {"agente": agente, "tipo": tipo, "club_id": club_id, "institucion_id": inst_id, "titulo": titulo,
            "url_fuente": cap.url, "hash_sha256": cap.sha256, "http_status": cap.http,
            "propuesta": propuesta or {}, "veto_juridico": "; ".join(veto) or None,
            "estado": "bloqueada_legal" if veto else "pendiente"}
    db().table("cola_revision").insert(fila).execute()
    return "bloqueado_legal" if veto else "nuevo"


# Objetivos: solo fuentes oficiales/públicas. Cada una apunta a UNA página concreta.
OBJETIVOS = [
    {"club": "brown", "titulo": "Boletín Oficial Alte. Brown - Enero 2026 (decretos)",
     "url": "https://files.brown.gob.ar/brown-web/bundles/site/pdf/boletin_oficial/PQ-Enero-Decretos-2026.pdf"},
    {"club": "brown", "titulo": "Ficha del club en el padrón web de FABA",
     "url": "https://basquetadaptado.com.ar/clubes/instituto-municipal-del-deporte-almirante-brown/"},
    {"inst": "faba", "titulo": "Autoridades FABA (web oficial)", "url": "https://basquetadaptado.com.ar/autoridades/"},
    {"inst": "copar", "titulo": "Autoridades COPAR (web oficial)", "url": "https://www.coparg.org.ar/nosotros/"},
]


def ciclo():
    clubes, insts = mapa_slugs("clubes"), mapa_slugs("instituciones")
    ej = db().table("agente_ejecuciones").insert({"agente": "rastreador", "objetivos": len(OBJETIVOS)}).execute()
    ej_id = ej.data[0]["id"] if ej.data else None
    ok = bloq = err = 0
    detalle = []
    for o in OBJETIVOS:
        cid, iid = clubes.get(o.get("club")), insts.get(o.get("inst"))
        if (cid is None) == (iid is None):
            err += 1; detalle.append({"url": o["url"], "resultado": "destino_inexistente"}); continue
        cap = capturar(o["url"])
        time.sleep(PAUSA_SEG)
        if cap.bloqueada:
            bloq += 1; detalle.append({"url": o["url"], "resultado": f"bloqueado_{cap.http}"}); continue
        if not cap.utilizable:
            err += 1; detalle.append({"url": o["url"], "resultado": cap.motivo or f"http_{cap.http}"}); continue
        r = proponer("rastreador", "documento_nuevo", o["titulo"], cap, cid, iid)
        ok += 1; detalle.append({"url": o["url"], "resultado": r})
    if ej_id:
        db().table("agente_ejecuciones").update({"fin": datetime.now(timezone.utc).isoformat(), "ok": ok, "bloqueados": bloq, "errores": err,
                                                 "detalle": {"objetivos": detalle}}).eq("id", ej_id).execute()
    print(f"ok={ok} bloqueados={bloq} errores={err}  (todo queda en cola_revision para revisión humana)")


if __name__ == "__main__":
    ciclo()


if __name__ == "__main__":
    ejecutar_orquestador_resiliente()
