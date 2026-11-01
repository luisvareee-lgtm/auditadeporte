import unittest
from datetime import date
from unittest import mock
import mesa, ingesta_redes as ing, orquestador_bots_audita as o

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><item><title>Rifa para el viaje a Santa Fe</title>
<link>https://www.fabasite.org.ar/n/1</link><pubDate>Fri, 30 Oct 2026 10:00:00 +0000</pubDate>
<description>&lt;p&gt;Sorteo de una camiseta. Alias: club.basquet&lt;/p&gt;</description></item></channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Balance 2025</title><link rel="alternate" href="https://x.gob.ar/b"/>
<published>2026-10-01T10:00:00Z</published><summary>Se publica el balance</summary></entry></feed>"""

def item(**k):
    d = dict(tipo="documento_nuevo", titulo="Autoridades", url_fuente="https://x.gob.ar/a/b", hash_sha256="a"*64,
             http_status=200, propuesta={}, texto=""); d.update(k); return d

class T(unittest.TestCase):
    def test_rss_y_atom(self):
        r = ing.parsear_feed(RSS); self.assertEqual(r[0]["fecha"], "2026-10-30"); self.assertNotIn("<p>", r[0]["texto"])
        self.assertEqual(ing.parsear_feed(ATOM)[0]["link"], "https://x.gob.ar/b")
    def test_rechaza_xml_malicioso(self):
        with self.assertRaises(ValueError): ing.parsear_feed(b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>')
    def test_clasifica_solo_hechos(self):
        c = ing.clasificar("Rifa para viajar a la gira. Alias club.x")
        self.assertTrue(c["menciona_colecta"]); self.assertIn("viaje", c["temas"])
        self.assertFalse(ing.clasificar("Entrenamiento del martes")["menciona_colecta"])
    def test_extracto_280(self):
        self.assertLessEqual(len(ing.extracto("palabra " * 100)), 280)
    def test_voto_juridico_y_datos_bloquean(self):
        v = mesa.evaluar(item(texto="Hubo una estafa"))
        self.assertEqual(mesa.decidir(v)[0], "bloqueada_legal")
        v = mesa.evaluar(item(texto="Presidente DNI 30.123.456"))
        self.assertEqual(mesa.decidir(v)[0], "bloqueada_legal")
    def test_fuente_portada_observa_no_bloquea(self):
        v = mesa.evaluar(item(url_fuente="https://x.gob.ar/"))
        estado, obs = mesa.decidir(v); self.assertEqual(estado, "pendiente"); self.assertTrue(any("portada" in x for x in obs))
    def test_sin_hash_veta_pero_no_es_legal(self):
        estado, obs = mesa.decidir(mesa.evaluar(item(hash_sha256=None))); self.assertEqual(estado, "pendiente"); self.assertTrue(obs)
    def test_contable_suma(self):
        p = {"items": [{"monto": 100}, {"monto": 50}], "total": 160}
        self.assertEqual(mesa.v_contable(item(propuesta=p))["voto"], "vetar")
        p["total"] = 150; self.assertEqual(mesa.v_contable(item(propuesta=p))["voto"], "aprobar")
    def test_vigencia(self):
        self.assertEqual(mesa.v_vigencia(item(propuesta={"fecha_posteo": "2024-01-01"}), hoy=date(2026, 11, 1))["voto"], "observar")
        self.assertEqual(mesa.v_vigencia(item(propuesta={"fecha_posteo": "2027-01-01"}), hoy=date(2026, 11, 1))["voto"], "vetar")
    def test_editorial_extracto(self):
        self.assertEqual(mesa.v_editorial(item(tipo="novedad_red", propuesta={"extracto": "x" * 300}))["voto"], "vetar")
    def test_pipeline_guarda_votos_en_tablas_privadas(self):
        c = mock.MagicMock()
        c.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        c.table.return_value.insert.return_value.execute.return_value.data = [{"id": "uuid-1"}]
        cap = o.Captura("https://x.gob.ar/a/b", 200, b"z", "a" * 64)
        with mock.patch.object(o, "db", return_value=c):
            self.assertEqual(o.proponer("r", "documento_nuevo", "Nómina", cap, club_id="u"), "nuevo")
        self.assertEqual({x.args[0] for x in c.table.call_args_list}, {"cola_revision", "agente_votos"})
    def test_feed_bloqueado_se_registra_sin_evadir(self):
        with mock.patch.object(o, "capturar", return_value=o.Captura("u", 403, motivo="http_403")):
            self.assertEqual(ing.procesar_feed({"url": "u", "club": "a", "plataforma": "web"}, {"a": 1}, {})["resultado"], "bloqueado")
if __name__ == "__main__": unittest.main()
