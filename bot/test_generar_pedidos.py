import unittest
from unittest import mock

import generar_pedidos as g
import orquestador_bots_audita as o
from prueba_util import FakeDB


class T(unittest.TestCase):
    def test_texto_y_cola(self):
        j = {"slug": "muni-x", "nombre": "Municipalidad de X", "estado": "no_publica", "motivo": "m", "sitio_web": "https://x.gob.ar/",
             "pedido": {"base": "Constitución Nacional", "norma": "ordenanza municipal", "plazo": "un plazo razonable",
                        "reclamo": "amparo por mora", "provincial": "Ley 12.475 (Poder Ejecutivo)"}}
        t = g.texto_pedido(j)
        self.assertIn("Municipalidad de X", t); self.assertIn("Ley 12.475", t); self.assertIn("un plazo razonable", t)
        self.assertNotIn("(Poder Ejecutivo)", t)
        datos = {"jurisdicciones": [j, {**j, "slug": "muni-y", "estado": "publica"}]}
        fdb = FakeDB({"instituciones": [{"id": "i1", "slug": "muni-x"}, {"id": "i2", "slug": "muni-y"}], "cola_revision": [], "agente_votos": []})
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(g.o, "db", return_value=fdb), \
             mock.patch.object(g.json, "load", return_value=datos), mock.patch("builtins.open", mock.mock_open(read_data="{}")):
            g.main(); g.main()
        cola = fdb.tablas["cola_revision"]
        self.assertEqual(len(cola), 1)                                   # solo la que no publica, y sin duplicar
        self.assertEqual(cola[0]["estado"], "pendiente")


if __name__ == "__main__":
    unittest.main()
