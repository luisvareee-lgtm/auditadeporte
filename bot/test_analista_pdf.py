import io
import shutil
import unittest

import analista_pdf as a


def pdf_texto(lineas):
    """PDF mínimo con texto real (Helvetica), sin librerías externas."""
    flujo = "BT /F1 11 Tf 60 780 Td 14 TL " + " ".join(f"({l}) '" for l in lineas) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(flujo)} >>\nstream\n{flujo}\nendstream"]
    out, pos = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        pos.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{p:010d} 00000 n \n" for p in pos)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF"
    return out.encode("latin-1")


class Temas(unittest.TestCase):
    def t(self, txt):
        return {x[0] for x in a.coincidencias(a.normalizar(txt))}

    def test_temas(self):
        self.assertIn("juegos_bonaerenses", self.t("Gastos de la final de los Juegos Bonaerenses 2026"))
        self.assertIn("instituto_deporte", self.t("a pedido del Instituto Municipal del Deporte"))
        self.assertIn("deporte_adaptado", self.t("equipo de básquet en silla de ruedas"))
        self.assertIn("viajes_deportivos", self.t("contratación de micros para el traslado de la delegación al torneo"))
        self.assertIn("discapacidad_deporte", self.t("subsidio a la escuela deportiva para personas con discapacidad"))

    def test_tributaria_no_cuenta_discapacidad(self):
        self.assertNotIn("discapacidad_deporte", self.t("ORDENANZA FISCAL 2026. Exímese a entidades deportivas y a personas con discapacidad"))

    def test_relevancia_viajes(self):
        solo_viaje = [{"tema": "viajes_deportivos", "montos": []}]
        self.assertFalse(a.es_relevante(solo_viaje))
        self.assertTrue(a.es_relevante([{"tema": "viajes_deportivos", "montos": ["$ 100.000"]}]))
        self.assertTrue(a.es_relevante([{"tema": "juegos_bonaerenses", "montos": []}]))

    def test_montos(self):
        t = "por un monto de $ 3.450.000,00 y U$S 240.000 (dólares)"
        self.assertEqual(a.montos_cerca(t, 0, 5), ["$ 3.450.000,00", "U$S 240.000"])


@unittest.skipUnless(a.disponible(), "falta pypdfium2")
class Pdf(unittest.TestCase):
    def test_pdf_con_texto_y_captura(self):
        data = pdf_texto(["DECRETO 900 - Otorgase un subsidio por $ 1.250.000,00", "al equipo de deporte adaptado",
                          "para los Juegos Bonaerenses 2026."])
        r = a.analizar(data, "https://ejemplo.gob.ar/d.pdf", "ab" * 32, ocr=False)
        self.assertEqual(r["paginas"], 1)
        temas = a.temas_de(r["hallazgos"])
        self.assertIn("deporte_adaptado", temas); self.assertIn("juegos_bonaerenses", temas)
        self.assertIn("$ 1.250.000,00", r["hallazgos"][0]["montos"])
        self.assertEqual(len(r["capturas"]), 1)
        img, meta = r["capturas"][0]
        self.assertEqual(img[:2], b"\xff\xd8"); self.assertEqual(meta["pagina"], 1)

    def test_pdf_sin_temas(self):
        r = a.analizar(pdf_texto(["Ordenanza de transito y estacionamiento medido"]), ocr=False)
        self.assertEqual(r["hallazgos"], []); self.assertEqual(r["capturas"], [])

    @unittest.skipUnless(shutil.which("tesseract"), "falta tesseract")
    def test_escaneo_con_ocr(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img)
        f = a._fuente(34)
        for k, l in enumerate(["Instituto Municipal del Deporte:", "traslado de la delegacion de basquet en",
                               "silla de ruedas a los Juegos Bonaerenses"]):
            d.text((80, 120 + 70 * k), l, fill="black", font=f)
        buf = io.BytesIO(); img.save(buf, "PDF", resolution=150)
        r = a.analizar(buf.getvalue(), ocr=True)
        self.assertEqual(r["paginas_ocr"], 1)
        self.assertIn("juegos_bonaerenses", a.temas_de(r["hallazgos"]))


if __name__ == "__main__":
    unittest.main()
