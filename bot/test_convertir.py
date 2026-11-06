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


if __name__ == "__main__":
    unittest.main()
