import unittest
from unittest import mock

import cargar_fuentes as cf
import orquestador_bots_audita as o
from prueba_util import FakeDB


class T(unittest.TestCase):
    def test_catalogo_valido_y_cubre_todos_los_clubes(self):
        cat = cf.catalogo()
        self.assertEqual(cf.validar(cat), [])
        self.assertEqual(len(cat["clubes"]), 25)
        urls = [f["url"] for j in cat["jurisdicciones"].values() for f in j["fuentes"]]
        self.assertEqual(len(urls), len(set(urls)))                      # url única en fuentes_monitoreadas

    def test_carga_idempotente(self):
        fdb = FakeDB({"clubes": [{"slug": s} for s in cf.catalogo()["clubes"]], "instituciones": [], "fuentes_monitoreadas": []})
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(cf.o, "db", return_value=fdb), \
             mock.patch("sys.argv", ["x"]):
            cf.main(); cf.main()
        self.assertEqual(len(fdb.tablas["fuentes_monitoreadas"]), 35)
        self.assertTrue(all(f["institucion_id"] for f in fdb.tablas["fuentes_monitoreadas"]))

    def test_jurisdicciones_de(self):
        self.assertIn("muni-almirante-brown", cf.jurisdicciones_de("almirante-brown"))
        self.assertEqual(cf.jurisdicciones_de("no-existe"), [])


if __name__ == "__main__":
    unittest.main()
