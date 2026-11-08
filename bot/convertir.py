"""Convierte un documento cargado a PDF para que el analista lo lea página por página y saque capturas.
PDF: tal cual. Imágenes (escaneos): a PDF con Pillow. Word (.docx), Excel (.xlsx), PowerPoint (.pptx), HTML y texto:
primero con MarkItDown (Microsoft, código abierto), que conserva las tablas y no necesita LibreOffice. Planillas
(.xlsx, .csv): fila por fila como "Encabezado: valor". El texto se pasa a un PDF con texto real (reportlab). Formatos viejos (.doc, .xls, .odt, .ods, .rtf) o si MarkItDown falla:
LibreOffice sin interfaz. El archivo original no se modifica: su huella SHA-256 es la que se registra."""
import io
import os
import shutil
import subprocess
import tempfile

IMAGENES = {"jpg", "jpeg", "png", "tif", "tiff", "webp"}
OFICINA = {"doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "csv", "txt", "pptx", "html", "htm"}
CON_MARKITDOWN = {"docx", "pptx", "html", "htm"}   # las planillas siguen fila por fila ("Encabezado: valor")


def texto_markitdown(datos: bytes, ext: str):
    """Texto en Markdown (tablas incluidas) o None si MarkItDown no está o no pudo."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return None
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "documento." + ext)
        open(ruta, "wb").write(datos)
        try:
            t = MarkItDown().convert(ruta).text_content or ""
        except Exception:
            return None
    t = t.strip()
    return t if len(t) >= 20 else None


def texto_a_pdf(texto: str) -> bytes:
    """PDF A4 con texto real (seleccionable, sin OCR) usando reportlab. Si no está reportlab, LibreOffice."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError:
        return _convertir(texto.encode("utf-8"), "txt", "pdf")
    import textwrap
    fuente = "Helvetica"
    for ruta in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"):
        try:
            pdfmetrics.registerFont(TTFont("DejaVu", ruta)); fuente = "DejaVu"; break
        except Exception:
            continue
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    ancho, alto = A4
    y = alto - 50
    for ln in texto.replace("\r", "").split("\n"):
        for parte in textwrap.wrap(ln, 105, break_long_words=True, replace_whitespace=False) or [""]:
            if y < 50:
                c.showPage(); y = alto - 50
            c.setFont(fuente, 8.5)
            c.drawString(40, y, parte)
            y -= 11
    c.save()
    return buf.getvalue()


FORMATOS = {"pdf"} | IMAGENES | OFICINA


def formato_de(nombre: str, datos: bytes = b"") -> str:
    ext = os.path.splitext(nombre or "")[1].lower().lstrip(".")
    if datos[:5] == b"%PDF-":
        return "pdf"
    return "jpg" if ext == "jpeg" else ("tif" if ext == "tiff" else ext)


def imagen_a_pdf(datos: bytes) -> bytes:
    from PIL import Image, ImageSequence
    im = Image.open(io.BytesIO(datos))
    paginas = [p.convert("RGB") for p in ImageSequence.Iterator(im)]
    buf = io.BytesIO()
    paginas[0].save(buf, "PDF", resolution=200, save_all=True, append_images=paginas[1:])
    return buf.getvalue()


PLANILLAS = {"xls", "xlsx", "ods", "csv"}


def _filas_planilla(datos: bytes, ext: str) -> list:
    """[(hoja, [celdas])] leyendo los valores completos (al pasar una planilla a PDF, las celdas largas se cortan)."""
    import csv
    if ext == "csv":
        txt = datos.decode("utf-8-sig", "ignore")
        try:
            dialecto = csv.Sniffer().sniff(txt[:4000], delimiters=",;\t|")
        except csv.Error:
            dialecto = csv.excel
        return [("CSV", [c.strip() for c in fila]) for fila in csv.reader(io.StringIO(txt), dialecto)]
    if ext != "xlsx":            # xls y ods: LibreOffice los pasa a xlsx
        datos = _convertir(datos, ext, "xlsx")
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        for fila in ws.iter_rows(values_only=True):
            out.append((ws.title, ["" if v is None else str(v).strip() for v in fila]))
    return out


def planilla_a_pdf(datos: bytes, ext: str) -> bytes:
    """Cada fila como 'Encabezado: valor | ...', para que nada quede cortado y se pueda citar la fila."""
    filas = [(h, f) for h, f in _filas_planilla(datos, ext) if any(f)]
    lineas, enc, hoja_actual = [], None, None
    for n, (hoja, f) in enumerate(filas[:5000]):
        if hoja != hoja_actual:
            hoja_actual, enc = hoja, f
            lineas.append(f"=== Hoja: {hoja} ===")
            continue
        pares = [f"{(enc[i] if enc and i < len(enc) and enc[i] else f'Col {i + 1}')}: {v}" for i, v in enumerate(f) if v]
        lineas.append(f"Fila {n + 1} | " + " | ".join(pares))
    return texto_a_pdf("\n".join(lineas))


def _convertir(datos: bytes, ext: str, destino: str, timeout=180) -> bytes:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("falta LibreOffice para convertir ." + ext)
    with tempfile.TemporaryDirectory() as d:
        entrada = os.path.join(d, "documento." + ext)
        open(entrada, "wb").write(datos)
        filtro = "pdf" if destino == "pdf" else destino
        subprocess.run([soffice, f"-env:UserInstallation=file://{d}/perfil", "--headless", "--norestore",
                        "--convert-to", filtro, "--outdir", d, entrada],
                       check=True, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        salida = os.path.join(d, "documento." + destino)
        if not os.path.exists(salida):
            raise RuntimeError("LibreOffice no generó el archivo")
        return open(salida, "rb").read()


def a_pdf(datos: bytes, formato: str) -> bytes:
    f = (formato or "").lower()
    if datos[:5] == b"%PDF-" or f == "pdf":
        if datos[:5] != b"%PDF-":
            raise ValueError("el archivo dice ser PDF pero no lo es")
        return datos
    if f in IMAGENES:
        return imagen_a_pdf(datos)
    if f == "txt":
        return texto_a_pdf(datos.decode("utf-8", "ignore"))
    if f in CON_MARKITDOWN:
        t = texto_markitdown(datos, f)
        if t:
            return texto_a_pdf(t)
    if f in PLANILLAS:
        return planilla_a_pdf(datos, f)
    if f in OFICINA:
        return _convertir(datos, f, "pdf")
    raise ValueError(f"formato no admitido: .{f}")
