import os
import unittest
from datetime import date
from unittest import mock

import actualidad_redes as a
import orquestador_bots_audita as o
from prueba_util import FakeDB

HOY = date(2026, 11, 4)
CUENTA = {"username": "club_x", "followers_count": 900, "media_count": 120, "media": {"data": [
    {"timestamp": "2026-10-30T20:00:00+0000", "permalink": "https://www.instagram.com/p/A1/", "media_type": "IMAGE",
     "caption": "Gran triunfo por la Primera División de la Liga Nacional FABA. Juan Pérez 20 puntos"},
    {"timestamp": "2026-10-10T20:00:00+0000", "permalink": "https://www.instagram.com/p/A2/", "media_type": "IMAGE",
     "caption": "Rifa para el viaje a Córdoba! alias club.x.mp"},
    {"timestamp": "2026-05-01T20:00:00+0000", "permalink": "https://www.instagram.com/p/A3/", "media_type": "VIDEO",
     "caption": "Fecha 3 de 1ra división"},
    {"timestamp": "2024-01-01T20:00:00+0000", "permalink": "https://www.instagram.com/p/A4/", "media_type": "IMAGE",
     "caption": "Ascendimos a 2da división"}]}}


class T(unittest.TestCase):
    def test_analizar(self):
        r = a.analizar(CUENTA, HOY)
        self.assertEqual(r["ultimo_posteo"], "2026-10-30"); self.assertEqual(r["posteos_90d"], 2)
        self.assertEqual(r["divisiones"]["1ra"]["menciones"], 2)
        self.assertNotIn("2da", r["divisiones"])                         # posteo de hace más de un año
        self.assertEqual(r["novedades"][0]["marcas"], ["colecta", "viaje"])
        self.assertNotIn("Juan", str(r)); self.assertNotIn("alias club", str(r))   # ningún texto del posteo sale
        self.assertEqual(a.division_probable(r["divisiones"]), "1ra")
        self.assertIsNone(a.division_probable({"1ra": {"menciones": 1, "ultima": "x"}, "2da": {"menciones": 1, "ultima": "y"}}))

    def test_propone_division_y_novedad_sin_texto(self):
        fdb = FakeDB({"cola_revision": [], "agente_votos": []})
        dest = {"tipo": "club", "id": "c1", "slug": "club-x", "nombre": "Club X", "instagram": "club_x",
                "division": None, "estado_afiliacion": "a_confirmar"}
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(a.o, "db", return_value=fdb):
            c = a.proponer(dest, a.analizar(CUENTA, HOY))
        self.assertEqual(c, {"division": 1, "novedad": 1})
        cola = fdb.tablas["cola_revision"]
        self.assertTrue(all(x["estado"] in ("pendiente", "bloqueada_legal") for x in cola))
        self.assertNotIn("Juan", str(cola)); self.assertNotIn("Córdoba", str(cola)); self.assertNotIn("alias club", str(cola))

    def test_token_no_aparece_en_errores(self):
        with mock.patch.dict(os.environ, {"META_TOKEN": "EAASECRETO"}):
            self.assertEqual(a._sin_token("fallo con EAASECRETO"), "fallo con [token]")


if __name__ == "__main__":
    unittest.main()
