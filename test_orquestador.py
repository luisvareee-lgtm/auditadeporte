import unittest
from unittest import mock
import orquestador_bots_audita as o

def cap(**k):
    d = dict(url="https://x.y/a.pdf", http=200, contenido=b"hola", sha256="a"*64); d.update(k); return o.Captura(**d)

class T(unittest.TestCase):
    def cliente(self, previo=False):
        c = mock.MagicMock()
        c.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": 1}] if previo else []
        return c
    def test_juridico_veta_imputaciones(self):
        self.assertIn("termino_vetado:estafa", o.pre_filtro_juridico("Denuncian una ESTAFA en el club", "https://x.y"))
        self.assertIn("termino_vetado:corrupcion", o.pre_filtro_juridico("caso de corrupción", "https://x.y"))
    def test_juridico_datos_personales_y_fuente(self):
        self.assertTrue(o.pre_filtro_juridico("DNI 30.123.456", "https://x.y"))
        self.assertTrue(o.pre_filtro_juridico("CUIL 20-30123456-7", "https://x.y"))
        self.assertIn("sin_fuente_verificable", o.pre_filtro_juridico("texto neutro", ""))
    def test_juridico_texto_neutro_pasa(self):
        self.assertEqual(o.pre_filtro_juridico("Nómina de autoridades publicada el 2026-10-31", "https://x.y"), [])
    def test_no_confunde_palabras(self):
        self.assertEqual(o.pre_filtro_juridico("Robotica y arrobamiento", "https://x.y"), [])
    def test_proponer_va_a_cola_pendiente(self):
        c = self.cliente()
        with mock.patch.object(o, "db", return_value=c):
            self.assertEqual(o.proponer("rastreador", "documento_nuevo", "Boletín", cap(), club_id="u"), "nuevo")
        c.table.assert_any_call("cola_revision")
        fila = c.table.return_value.insert.call_args_list[0][0][0]
        self.assertEqual(fila["estado"], "pendiente")
    def test_proponer_veto_queda_bloqueada(self):
        c = self.cliente()
        with mock.patch.object(o, "db", return_value=c):
            self.assertEqual(o.proponer("rastreador", "documento_nuevo", "Estafa en el club", cap(), club_id="u"), "bloqueado_legal")
        self.assertEqual(c.table.return_value.insert.call_args_list[0][0][0]["estado"], "bloqueada_legal")
    def test_duplicado(self):
        with mock.patch.object(o, "db", return_value=self.cliente(previo=True)):
            self.assertEqual(o.proponer("r", "documento_nuevo", "t", cap(), club_id="u"), "duplicado")
    def test_bloqueo_no_se_evade(self):
        with mock.patch("urllib.request.urlopen", side_effect=o.urllib.error.HTTPError("u", 403, "f", {}, None)), \
             mock.patch.object(o, "_robots_permite", return_value=True):
            r = o.capturar("https://x.y")
        self.assertTrue(r.bloqueada); self.assertFalse(r.utilizable); self.assertIsNone(r.sha256)
    def test_robots(self):
        with mock.patch.object(o, "_robots_permite", return_value=False):
            self.assertEqual(o.capturar("https://x.y").motivo, "robots_no_permite")
    def test_nunca_toca_tablas_publicas(self):
        c = self.cliente()
        with mock.patch.object(o, "db", return_value=c):
            o.proponer("r", "documento_nuevo", "t", cap(), club_id="u")
        tablas = {call.args[0] for call in c.table.call_args_list}
        self.assertTrue(tablas <= {"cola_revision", "agente_votos"}, tablas)
if __name__ == "__main__": unittest.main()
