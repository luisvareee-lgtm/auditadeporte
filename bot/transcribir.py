"""Transcribe el audio de videos públicos de cuentas oficiales para poder clasificarlos como un posteo de texto.

Solo se transcriben videos cuyo texto ya menciona plata, pasajes, becas, torneos o el Estado (para no gastar horas
de máquina en cada reel). Usa faster-whisper con un modelo chico en la CPU del runner, en español. La transcripción
se usa en memoria para clasificar y se descarta: no se guarda ni el video ni el texto.
"""
import os
import re
import tempfile
import urllib.request

MAX_POR_CORRIDA = int(os.environ.get("VIDEOS_POR_CORRIDA", "6"))
MAX_BYTES = 80 * 1024 * 1024
RE_VALE_LA_PENA = re.compile(r"(?i)colect|rifa|alias|cbu|donac|ayud|pasaje|viaj|inscrip|beca|secretar|subsecret|mundial|"
                             r"parapanam|sudameric|torneo|necesitamos|sponsor|patrocin|aporte")
_modelo = [None]
_usados = [0]


def disponible() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def conviene(post: dict) -> bool:
    return (post.get("media_type") in ("VIDEO", "REELS") and bool(post.get("media_url"))
            and bool(RE_VALE_LA_PENA.search(post.get("caption") or "")) and _usados[0] < MAX_POR_CORRIDA)


def transcribir(url: str):
    """Texto hablado del video, o None. Respeta un tamaño máximo y no guarda nada en disco al terminar."""
    if not disponible():
        return None
    _usados[0] += 1
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "video.mp4")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AuditaDeporteBot/5.0 (observatorio civico)"})
            with urllib.request.urlopen(req, timeout=60) as r, open(ruta, "wb") as f:
                leidos = 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    leidos += len(b)
                    if leidos > MAX_BYTES:
                        return None
                    f.write(b)
            from faster_whisper import WhisperModel
            if _modelo[0] is None:
                _modelo[0] = WhisperModel(os.environ.get("WHISPER_MODELO", "base"), device="cpu", compute_type="int8")
            segs, _ = _modelo[0].transcribe(ruta, language="es", vad_filter=True)
            return " ".join(s.text.strip() for s in segs)[:6000] or None
        except Exception as e:
            print("  no se pudo transcribir un video:", str(e)[:100], flush=True)
            return None
