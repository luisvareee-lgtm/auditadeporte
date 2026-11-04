import importlib.util
import unittest
from datetime import datetime, timezone
from unittest import mock

import orquestador_bots_audita as o
from prueba_util import FakeDB


def cap(**k):
    d = dict(url="https://x.gob.ar/a.pdf", http=200, contenido=b"hola", sha256="a" * 64); d.update(k); return o.Captura(**d)


def pdf_con_texto(texto: str) -> bytes:
    """PDF mínimo válido con una línea de texto (para probar la extracción sin librerías extra)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, ob in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n".encode() + ob + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{n:010d} 00000 n \n".encode() for n in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    return out


class T(unittest.TestCase):
    def cliente(self, previo=False):
        c = mock.MagicMock()
        c.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": 1}] if previo else []
        return c

    # ---- jurídico y captura honesta (v5, siguen vigentes)
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
        fila = c.table.return_value.insert.call_args_list[0][0][0]
        self.assertEqual(fila["estado"], "pendiente")

    def test_proponer_veto_queda_bloqueada(self):
        c = self.cliente()
        with mock.patch.object(o, "db", return_value=c):
            self.assertEqual(o.proponer("rastreador", "documento_nuevo", "Estafa en el club", cap(), club_id="u"), "bloqueado_legal")

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
            r = o.capturar("https://x.y")
        self.assertEqual(r.motivo, "robots_no_permite"); self.assertTrue(r.bloqueada)

    def test_archivo_grande_no_se_hashea(self):
        resp = mock.MagicMock(); resp.__enter__.return_value = resp; resp.getcode.return_value = 200
        resp.read.return_value = b"x" * (o.MAX_BYTES + 1)
        with mock.patch("urllib.request.urlopen", return_value=resp), mock.patch.object(o, "_robots_permite", return_value=True):
            r = o.capturar("https://x.y/big.pdf")
        self.assertEqual(r.motivo, "archivo_demasiado_grande"); self.assertIsNone(r.sha256)

    # ---- analista documental
    def test_cuit_y_expedientes(self):
        bueno = next(f"30-1234567{d}-{v}" for d in range(10) for v in range(10) if o.cuit_valido(f"30-1234567{d}-{v}"))
        t = f"Visto el EX-2026-12345678- -APN-DGD#MS y el Expte. N° 4012-1234/2025, CUIT {bueno} y DNI 30.123.456"
        self.assertIn("EX-2026-12345678--APN-DGD#MS", o.extraer_expedientes(t))
        self.assertIn("EXP 4012-1234/2025", o.extraer_expedientes(t))
        self.assertEqual(o.extraer_cuits_entidades(t), [bueno])
        self.assertEqual(o.extraer_cuits_entidades("20-30123456-7"), [])      # personas: nunca se extraen

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf no instalado")
    def test_pdf_con_texto_y_sin_texto(self):
        largo = "Decreto 12 2026 Visto el EX-2026-12345678- -APN-DGD#MS " + "subsidio al club para traslados " * 8
        ind, req, motivo = o.analizar_contenido(cap(contenido=pdf_con_texto(largo)))
        self.assertTrue(ind["es_pdf"]); self.assertFalse(req); self.assertIn("EX-2026-12345678--APN-DGD#MS", ind["expedientes"])
        ind, req, motivo = o.analizar_contenido(cap(contenido=pdf_con_texto("")))
        self.assertTrue(req); self.assertEqual(motivo, "pdf_sin_capa_de_texto")

    def test_html_sin_texto_marca_revision(self):
        ind, req, motivo = o.analizar_contenido(cap(contenido=b"<html><script>var a=1</script><div id=app></div></html>"))
        self.assertTrue(req); self.assertEqual(motivo, "pagina_sin_texto_legible")

    # ---- sitemap
    def test_sitemap(self):
        xml = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://x.gob.ar/resoluciones/r1.pdf</loc><lastmod>2026-10-30</lastmod></url>
          <url><loc>https://x.gob.ar/noticias/n1</loc><lastmod>2026-10-30</lastmod></url>
          <url><loc>https://otro.com/resoluciones/r2.pdf</loc><lastmod>2026-10-30</lastmod></url>
          <url><loc>https://x.gob.ar/resoluciones/viejo.pdf</loc><lastmod>2025-01-01</lastmod></url></urlset>"""
        f = {"url": "https://x.gob.ar/", "patron_url": "resolucion", "ultima_revision": "2026-10-01T00:00:00+00:00"}
        with mock.patch.object(o, "capturar", return_value=cap(contenido=xml)), mock.patch.object(o.time, "sleep"):
            self.assertEqual(o.descubrir_sitemap(f, [10]), ["https://x.gob.ar/resoluciones/r1.pdf"])
        with self.assertRaises(ValueError):
            o.parsear_sitemap(b'<!DOCTYPE x [<!ENTITY a "b">]><urlset/>')

    # ---- fuentes y ciclo
    def test_vencida(self):
        m = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.assertTrue(o.vencida({"ultima_revision": None}, m))
        self.assertFalse(o.vencida({"ultima_revision": "2026-11-02T12:00:00+00:00", "frecuencia_dias": 7}, m))
        self.assertTrue(o.vencida({"ultima_revision": "2026-10-20T12:00:00+00:00", "frecuencia_dias": 7}, m))

    def test_sin_tabla_usa_respaldo(self):
        fdb = FakeDB(faltantes={"fuentes_monitoreadas"})
        with mock.patch.object(o, "db", return_value=fdb):
            self.assertIsNone(o.cargar_fuentes())

    def test_estado_de_la_fuente(self):
        fdb = FakeDB({"fuentes_monitoreadas": [{"id": "f1", "estado": "activa", "fallos_consecutivos": 2}]})
        with mock.patch.object(o, "db", return_value=fdb):
            o.actualizar_fuente({"id": "f1", "estado": "activa", "fallos_consecutivos": 2}, cap(http=500, contenido=b"", sha256=None))
            self.assertEqual(fdb.tablas["fuentes_monitoreadas"][0]["estado"], "caida")
            o.actualizar_fuente({"id": "f1", "estado": "caida", "fallos_consecutivos": 3}, cap(http=403, contenido=b"", sha256=None))
            self.assertEqual(fdb.tablas["fuentes_monitoreadas"][0]["estado"], "bloqueada_robots")
            o.actualizar_fuente({"id": "f1", "estado": "caida", "fallos_consecutivos": 3}, cap())
            self.assertEqual(fdb.tablas["fuentes_monitoreadas"][0]["fallos_consecutivos"], 0)

    def _ciclo(self, fdb, contenido):
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(o.time, "sleep"), \
             mock.patch.object(o, "capturar", side_effect=lambda u, **k: cap(url=u, contenido=contenido,
                                                                              sha256=o.hashlib.sha256(contenido).hexdigest())):
            o.ciclo()

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf no instalado")
    def test_ciclo_nuevo_luego_sin_cambios_luego_cambio(self):
        fdb = FakeDB({"fuentes_monitoreadas": [{"id": "f1", "club_id": "c1", "institucion_id": None, "nombre": "Boletín",
                                                "url": "https://x.gob.ar/b.pdf", "tipo": "boletin_oficial", "estado": "activa",
                                                "frecuencia_dias": 7, "portal_origen": "boletin_municipal", "usa_sitemap": False}]})
        texto = pdf_con_texto("Resolucion del concejo deliberante sobre subsidio al deporte adaptado " * 4)
        self._ciclo(fdb, texto)
        self.assertEqual([r["tipo"] for r in fdb.tablas["cola_revision"]], ["documento_nuevo"])
        fdb.tablas["fuentes_monitoreadas"][0]["ultima_revision"] = None          # forzar nueva pasada
        self._ciclo(fdb, texto)
        self.assertEqual(len(fdb.tablas["cola_revision"]), 1)                        # sin cambios: no se repite
        fdb.tablas["fuentes_monitoreadas"][0]["ultima_revision"] = None
        self._ciclo(fdb, pdf_con_texto("Resolucion modificada: nuevo texto del documento oficial publicado " * 4))
        ult = fdb.tablas["cola_revision"][-1]
        self.assertEqual(ult["tipo"], "documento_cambio"); self.assertTrue(ult["propuesta"]["hash_anterior"])
        self.assertEqual(ult["propuesta"]["fuente_id"], "f1")
        self.assertTrue(fdb.escrituras() <= {"cola_revision", "agente_votos", "agente_ejecuciones",
                                             "fuentes_monitoreadas", "fuente_urls_vistas"}, fdb.escrituras())

    def test_redes_no_las_procesa_el_rastreador(self):
        fdb = FakeDB({"fuentes_monitoreadas": [{"id": "f2", "tipo": "red_oficial", "estado": "activa", "url": "https://y.org/feed"}]})
        with mock.patch.object(o, "db", return_value=fdb):
            self.assertEqual(o.cargar_fuentes(), [])


if __name__ == "__main__":
    unittest.main()
