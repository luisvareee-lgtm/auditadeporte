import hashlib
import unittest
from unittest import mock

import orquestador_bots_audita as o
from prueba_util import FakeDB

INDICE = b"""<html><body><a href="/">Inicio</a> <a href="https://www.facebook.com/muni">fb</a>
<a href="/boletin/2026/boletin-120.pdf">Bolet\xc3\xadn 120</a> <a href="/boletin/2026/boletin-121.pdf">Bolet\xc3\xadn 121</a>
<a href="/decreto-455-2026/">Decreto 455/2026</a> <a href="https://otro-sitio.com/nota.pdf">externo</a>
<a href="/noticias/fiesta">Fiesta</a> <p>Actualizado 04/11/2026 10:35</p></body></html>"""
PAGINAS = {
    "https://muni.gob.ar/boletin/2026/boletin-120.pdf": b"<html>Decreto 12: otorgase subsidio a la Asociacion CEDIMA para viaticos del equipo de basquet adaptado</html>",
    "https://muni.gob.ar/boletin/2026/boletin-121.pdf": b"<html>Decreto 13: pavimentacion de calles del barrio norte, adjudicacion a empresa constructora</html>",
    "https://muni.gob.ar/decreto-455-2026/": b"<html>Programa municipal de deporte inclusivo para personas con discapacidad: polideportivo</html>",
}


def cap(u, data):
    return o.Captura(u, 200, data, hashlib.sha256(data).hexdigest())


class T(unittest.TestCase):
    def test_enlaces_documento(self):
        e = o.enlaces_documento(INDICE, "https://muni.gob.ar/boletin/")
        self.assertEqual(e, list(PAGINAS))                                  # ni redes, ni externos, ni noticias

    def test_relevancia(self):
        al = {"cedima": "cedima"}
        self.assertEqual(o.relevancia("subsidio a CEDIMA para basquet adaptado", al),
                         ["deporte_y_discapacidad", "menciona_club:cedima", "menciona_fondos"])
        self.assertEqual(o.relevancia("pavimentacion y discapacidad visual en semaforos", al), [])   # sin deporte, no
        self.assertEqual(o.relevancia("convenio con FABA", {}), ["menciona_faba_copar_enard", "menciona_fondos"])

    def test_hash_estable_ignora_fechas(self):
        a = o.hash_estable(cap("u", b"<p>Boletin de hoy 04/11/2026 10:35 visitas 120</p>"))
        b = o.hash_estable(cap("u", b"<p>Boletin de hoy 05/11/2026 11:02 visitas 133</p>"))
        self.assertEqual(a, b)

    def test_indice_propone_solo_lo_relevante(self):
        fdb = FakeDB({"cola_revision": [], "agente_votos": [], "fuente_urls_vistas": []})
        f = {"id": "f1", "url": "https://muni.gob.ar/boletin/", "nombre": "Boletín muni", "tipo": "boletin_oficial",
             "institucion_id": "i1", "club_id": None}
        club = {"id": "c1", "slug": "cedima", "nombre": "CEDIMA"}
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(o.time, "sleep"), \
             mock.patch.object(o, "capturar", side_effect=lambda u, **k: cap(u, PAGINAS[u])):
            r = o.procesar_indice(f, cap(f["url"], INDICE), {}, [50], {"cedima": "cedima"}, {"cedima": club})
            vistas = {x["url"]: x["hash_sha256"] for x in fdb.tablas["fuente_urls_vistas"]}
            r2 = o.procesar_indice(f, cap(f["url"], INDICE), vistas, [50], {"cedima": "cedima"}, {"cedima": club})
        self.assertEqual(sorted(r), ["no_relevante", "nuevo", "nuevo"])
        self.assertEqual(r2, [])                                              # ya leídos: no se vuelven a bajar
        cola = fdb.tablas["cola_revision"]
        self.assertEqual(len(cola), 2)
        pav = [c for c in cola if "121" in c["url_fuente"]]
        self.assertFalse(pav)
        ced = next(c for c in cola if "120" in c["url_fuente"])
        self.assertEqual(ced["club_id"], "c1")                                # se asigna al club que menciona
        self.assertIn("menciona_club:cedima", ced["propuesta"]["coincidencias"])
        self.assertFalse(any(c["url_fuente"] == f["url"] for c in cola))     # la portada del índice no se propone


if __name__ == "__main__":
    unittest.main()
