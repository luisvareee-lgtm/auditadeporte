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
        self.assertEqual(c, {"division": 1, "novedad": 1, "inactiva": 0, "contraste": 1})
        cola = fdb.tablas["cola_revision"]
        self.assertTrue(all(x["estado"] in ("pendiente", "bloqueada_legal") for x in cola))
        self.assertNotIn("Juan", str(cola)); self.assertNotIn("Córdoba", str(cola)); self.assertNotIn("alias club", str(cola))

    def test_aviso_de_inactividad(self):
        fdb = FakeDB({"cola_revision": [], "agente_votos": []})
        dest = {"tipo": "club", "id": "c1", "slug": "club-x", "nombre": "Club X", "instagram": "club_x",
                "division": "1ra", "estado_afiliacion": "activo"}
        vieja = {"username": "club_x", "media": {"data": [{"timestamp": "2026-01-02T10:00:00+0000",
                                                             "permalink": "https://www.instagram.com/p/Z/", "caption": "hola"}]}}
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(a.o, "db", return_value=fdb):
            c = a.proponer(dest, a.analizar(vieja, HOY))
        self.assertEqual(c["inactiva"], 1)

    def test_token_no_aparece_en_errores(self):
        with mock.patch.dict(os.environ, {"META_TOKEN": "EAASECRETO"}):
            self.assertEqual(a._sin_token("fallo con EAASECRETO"), "fallo con [token]")


if __name__ == "__main__":
    unittest.main()


CLUBES = [{"id": i, "slug": s, "nombre": n, "instagram": ig, "division": d, "estado_afiliacion": "activo"} for i, s, n, ig, d in [
    ("ab", "almirante-brown", "Instituto Municipal del Deporte Almirante Brown", "alte.brown1rabsr", "1ra"),
    ("ag", "brown-alta-gracia", "Brown de Alta Gracia", None, None),
    ("ce", "cedima", "CEDIMA", "cedima.oficial", None),
    ("cs", "cilsa-santa-fe", "CILSA Santa Fe", "cilsaong", None),
    ("cb", "cilsa-boca-juniors", "CILSA Boca Juniors", "cilsaong", None),
    ("cr", "crol-rosario", "CROL (Club Rosarino de Lisiados)", None, None),
    ("fu", "fudituc", "Fu.Di.Tuc", None, None),
    ("av", "municipalidad-avellaneda", "Municipalidad de Avellaneda", None, None)]]

FABA = {"username": "basquetadaptadofaba", "media": {"data": [
    {"timestamp": "2026-10-20T12:00:00+0000", "permalink": "https://www.instagram.com/p/F1/",
     "caption": "Resultados Primera División: CEDIMA 60 - Almirante Brown 58. CILSA Santa Fe vs CROL"},
    {"timestamp": "2026-10-13T12:00:00+0000", "permalink": "https://www.instagram.com/p/F2/",
     "caption": "Fixture de 1ra división: @cedima.oficial recibe a Fu.Di.Tuc. Brown visita a CILSA"},
    {"timestamp": "2026-09-01T12:00:00+0000", "permalink": "https://www.instagram.com/p/F3/",
     "caption": "Segunda División: Avellaneda y Brown de Alta Gracia. Gran fecha en Avellaneda"},
    {"timestamp": "2026-08-01T12:00:00+0000", "permalink": "https://www.instagram.com/p/F4/",
     "caption": "Torneo 2da división: Municipalidad de Avellaneda campeón"},
    {"timestamp": "2026-07-01T12:00:00+0000", "permalink": "https://www.instagram.com/p/F5/",
     "caption": "Ascensos: CROL de segunda división pasa a primera división"}]}}


class TFaba(unittest.TestCase):
    def test_alias_ambiguos_se_descartan(self):
        al = a.alias_de_clubes(CLUBES)
        self.assertNotIn("brown", al); self.assertNotIn("cilsa", al)
        self.assertEqual(al["almirante brown"], "ab"); self.assertEqual(al["brown de alta gracia"], "ag")
        self.assertEqual(al["cedima"], "ce"); self.assertEqual(al["fuditu" + "c"], "fu"); self.assertEqual(al["avellaneda"], "av")
        self.assertNotIn("@cilsaong", al); self.assertEqual(al["@cedimaoficial"], "ce")

    def test_divisiones_desde_faba(self):
        d = a.divisiones_desde_faba(FABA, CLUBES, HOY)
        self.assertEqual(d["ce"]["1ra"]["menciones"], 2)
        self.assertEqual(d["ab"]["1ra"]["menciones"], 1)                 # el 2do posteo dice solo "Brown": ambiguo
        self.assertEqual(d["cs"]["1ra"]["menciones"], 1)                 # "CILSA" a secas no cuenta
        self.assertNotIn("cb", d)
        self.assertEqual(d["av"]["2da"]["menciones"], 2); self.assertEqual(d["ag"]["2da"]["menciones"], 1)
        self.assertNotIn("2da", d.get("cr", {}))                         # el posteo de ascensos nombra dos divisiones

    def test_propone_solo_con_dos_menciones_y_si_cambia(self):
        fdb = FakeDB({"cola_revision": [], "agente_votos": []})
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(a.o, "db", return_value=fdb):
            n = a.proponer_divisiones_faba(a.divisiones_desde_faba(FABA, CLUBES, HOY), CLUBES)
        titulos = [c["titulo"] for c in fdb.tablas["cola_revision"]]
        self.assertEqual(n, 2, titulos)                                   # CEDIMA (1ra) y Avellaneda (2da)
        self.assertTrue(any("CEDIMA" in t for t in titulos)); self.assertTrue(any("Avellaneda" in t for t in titulos))


class TContraste(unittest.TestCase):
    def _correr(self, fuentes, docs):
        fdb = FakeDB({"cola_revision": [], "agente_votos": [], "fuentes_monitoreadas": fuentes, "documentos_fuente": docs})
        dest = {"tipo": "club", "id": "c1", "slug": "club-x", "nombre": "Club X", "instagram": "club_x"}
        n = {"permalink": "https://www.instagram.com/p/A2/", "fecha": "2026-10-10", "tipo": "IMAGE", "marcas": ["colecta", "viaje"]}
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(a.o, "db", return_value=fdb):
            r = a.contraste_colecta(dest, n, a._cap(n["permalink"], n))
        return r, fdb.tablas["cola_revision"][-1]["propuesta"]["parametros"]

    def test_sin_fuentes(self):
        r, p = self._correr([], [])
        self.assertEqual(r, "nuevo"); self.assertEqual(p["resultado"], "sin_fuentes")
        self.assertIn("no es posible contrastar", p["dictamen"])

    def test_con_fuente_sin_documentos(self):
        _, p = self._correr([{"club_id": "c1", "nombre": "Boletín", "tipo": "boletin_oficial", "estado": "activa"}], [])
        self.assertEqual(p["resultado"], "sin_documentos")
        self.assertIn("no acredita que el acto no exista", p["dictamen"])
        for palabra in ("corrupci", "desv", "abandon", "mentir"):
            self.assertNotIn(palabra, p["dictamen"].lower())

    def test_con_documentos(self):
        _, p = self._correr([{"club_id": "c1", "nombre": "Boletín", "tipo": "boletin_oficial", "estado": "activa"}],
                            [{"club_id": "c1", "titulo": "Decreto 123 viáticos", "expediente_o_norma": "D-123/2026",
                              "url_fuente": "https://x.gob.ar/d", "portal_origen": "boletin_municipal",
                              "fecha_captura": "2026-09-01T00:00:00+00:00"}])
        self.assertEqual(p["resultado"], "con_documentos"); self.assertIn("D-123/2026", p["dictamen"])
