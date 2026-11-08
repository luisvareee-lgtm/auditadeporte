import io
import shutil
import unittest

import analista_pdf as a
import convertir as c


class Convertir(unittest.TestCase):
    def test_formato(self):
        self.assertEqual(c.formato_de("Boletin Julio.PDF"), "pdf")
        self.assertEqual(c.formato_de("x.jpeg"), "jpg")
        self.assertEqual(c.formato_de("raro.bin", b"%PDF-1.4"), "pdf")

    def test_rechaza_lo_que_no_es(self):
        with self.assertRaises(ValueError):
            c.a_pdf(b"hola", "pdf")
        with self.assertRaises(ValueError):
            c.a_pdf(b"x", "exe")

    def test_imagen(self):
        from PIL import Image
        b = io.BytesIO(); Image.new("RGB", (300, 200), "white").save(b, "PNG")
        self.assertEqual(c.a_pdf(b.getvalue(), "png")[:5], b"%PDF-")

    @unittest.skipUnless(shutil.which("soffice"), "falta LibreOffice")
    def test_word_y_planilla(self):
        import docx, openpyxl
        d = docx.Document(); d.add_paragraph("Subsidio al equipo de básquet en silla de ruedas para los Juegos Bonaerenses.")
        b = io.BytesIO(); d.save(b)
        self.assertIn("juegos_bonaerenses", a.temas_de(a.analizar(c.a_pdf(b.getvalue(), "docx"), ocr=False)["hallazgos"]))
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(["Proveedor", "Objeto", "Monto"]); ws.append(["X SA", "Traslado de la delegación de deporte adaptado a los Juegos Bonaerenses", "$ 2.500.000,00"])
        b = io.BytesIO(); wb.save(b)
        r = a.analizar(c.a_pdf(b.getvalue(), "xlsx"), ocr=False)
        self.assertIn("Proveedor: X SA", r["texto"])              # la celda larga no se corta
        self.assertIn("juegos_bonaerenses", a.temas_de(r["hallazgos"]))


class MarkItDown(unittest.TestCase):
    def test_word_con_tabla_sin_libreoffice(self):
        try:
            import markitdown  # noqa: F401
            from docx import Document
        except ImportError:
            self.skipTest("sin markitdown o python-docx")
        import io
        d = Document(); d.add_paragraph("Decreto 1234/2026. Otórgase un subsidio al club de básquet adaptado.")
        t = d.add_table(rows=2, cols=3)
        for i, fila in enumerate([("Beneficiario", "Concepto", "Monto"), ("Club Deportivo", "Sillas deportivas", "$ 1.800.000")]):
            for j, v in enumerate(fila):
                t.cell(i, j).text = v
        buf = io.BytesIO(); d.save(buf)
        pdf = c.a_pdf(buf.getvalue(), "docx")
        self.assertEqual(pdf[:5], b"%PDF-")
        import orquestador_bots_audita as o
        texto = o.texto_pdf(pdf) or ""
        self.assertIn("Sillas deportivas", texto)          # texto real, sin OCR
        self.assertIn("1.800.000", texto)


if __name__ == "__main__":
    unittest.main()
