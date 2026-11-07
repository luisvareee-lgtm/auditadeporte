import unittest

import orquestador_bots_audita as o
import rastreo_sitio as r


def pagina(html):
    import hashlib
    b = html.encode()
    return lambda url: o.Captura(url, 200, b, hashlib.sha256(b).hexdigest())


class Rastreo(unittest.TestCase):
    def setUp(self):
        o.PAUSA_SEG = 0
        self.cfg = r.SITIOS["subsecretaria-deportes"]

    def test_alcance(self):
        self.assertEqual(r.clase("https://www.argentina.gob.ar/jefatura/deportes/becas", self.cfg), "seccion")
        self.assertEqual(r.clase("https://www.argentina.gob.ar/noticias/algo", self.cfg), "hoja")
        self.assertEqual(r.clase("https://www.argentina.gob.ar/salud", self.cfg), "")
        self.assertEqual(r.clase("https://www.boletinoficial.gob.ar/detalleAviso/primera/1/20260101", self.cfg), "hoja")

    def test_enlaces_normaliza_y_filtra(self):
        html = ('<a href="/jefatura/deportes/becas/">B</a><a href="/jefatura/deportes/becas#x">B</a>'
                '<a href="https://www.facebook.com/x">F</a><a href="/files/res.pdf">R</a>')
        l = r.enlaces(html, "https://www.argentina.gob.ar/jefatura/deportes")
        self.assertEqual(l, ["https://www.argentina.gob.ar/jefatura/deportes/becas", "https://www.argentina.gob.ar/files/res.pdf"])

    def test_temas_seleccion_y_relevancia(self):
        hs = r.temas("Se otorgaron pasajes a la Seleccion Argentina de basquet sobre silla de ruedas para el Mundial")
        self.assertIn("seleccion_fondos", {h["tema"] for h in hs})
        self.assertTrue(r.es_relevante(hs))
        self.assertFalse(r.es_relevante(r.temas("Juegos Evita: inscripciones abiertas para futbol y hockey")))
        t = "Los Juegos Evita contaron con apoyo del ENARD para el boxeo"
        self.assertFalse(r.es_relevante(r.temas(t), t))

    def test_recorre_seccion_sin_salir_del_alcance(self):
        sitio = {"https://www.argentina.gob.ar/jefatura/deportes":
                 '<a href="/jefatura/deportes/federaciones">F</a><a href="/salud">S</a><a href="/noticias/n1">N</a>',
                 "https://www.argentina.gob.ar/jefatura/deportes/federaciones":
                 'Apoyo a la Federacion Argentina de Basquet en Silla de Ruedas (FABA): subsidio para la seleccion',
                 "https://www.argentina.gob.ar/noticias/n1": '<a href="/jefatura/deportes/otra">no se sigue desde una hoja</a>'}
        cap = lambda u: pagina(sitio.get(u, ""))(u)
        res = r.rastrear("subsecretaria-deportes", 50, prueba=True, capturar=cap)
        self.assertEqual(res["leidas"], 3)
        self.assertEqual(res["temas"].get("federaciones"), 1)

    def test_respeta_bloqueo(self):
        res = r.rastrear("subsecretaria-deportes", 5, prueba=True, capturar=lambda u: o.Captura(u, 403))
        self.assertEqual(res["bloqueadas"], 1)
        self.assertEqual(res["leidas"], 1)


if __name__ == "__main__":
    unittest.main()
