import hashlib
import io
import unittest

try:
    from PIL import Image
except ImportError:
    Image = None

import escudos_clubes as e


@unittest.skipIf(Image is None and not __import__("os").environ.get("CI"), "falta Pillow")
class Escudos(unittest.TestCase):
    def _jpg(self, tam=(600, 300), exif=True):
        im, b = Image.new("RGB", tam, (200, 30, 30)), io.BytesIO()
        ex = Image.Exif()
        ex[0x010E] = "dato que no tiene que salir"
        im.save(b, "JPEG", exif=ex if exif else None)
        return b.getvalue()

    def test_sale_webp_cuadrado_sin_metadatos_y_con_huella(self):
        webp, huella = e.normalizar_escudo(self._jpg())
        im = Image.open(io.BytesIO(webp))
        self.assertEqual((im.format, im.size), ("WEBP", (256, 256)))
        self.assertFalse(dict(im.getexif()))
        self.assertNotIn(b"dato que no tiene", webp)
        self.assertEqual(huella, hashlib.sha256(webp).hexdigest())
        self.assertEqual(im.convert("RGBA").getpixel((2, 2))[3], 0)          # el borde que sobra es transparente

    def test_misma_imagen_misma_huella(self):
        self.assertEqual(e.normalizar_escudo(self._jpg())[1], e.normalizar_escudo(self._jpg())[1])

    def test_rechaza_lo_que_no_es_imagen(self):
        with self.assertRaises(Exception):
            e.normalizar_escudo(b"<html><script>alert(1)</script></html>" * 50)


if __name__ == "__main__":
    unittest.main()
