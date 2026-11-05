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
        lejos = "Direccion de Discapacidad. " + "x " * 300 + "Secretaria de Deportes"
        self.assertEqual(o.relevancia(lejos, {}), [])                                                  # lejos: no
        fiscal = "Exencion de tasas a entidades deportivas y a personas con discapacidad segun articulo 45"
        self.assertEqual(o.relevancia(fiscal, {}), [])                                                 # ordenanza fiscal: no
        tribut = ("Ordenanza Impositiva 2026. Titulo 3: exenciones. Entidades deportivas y personas con discapacidad. "
                  + "x " * 400 + "Aportes y subsidios de terceros")
        self.assertEqual(o.relevancia(tribut, {}), [])                                                 # fondos lejos y tributaria
        self.assertEqual(o.relevancia("convenio con FABA", {}), ["menciona_faba_copar_enard", "menciona_fondos"])

    def test_menu_del_sitio_no_cuenta(self):
        pag = b"""<html><nav><a>Deportes</a><a>Discapacidad</a></nav><main><h1>Boleto estudiantil</h1>
        <p>Tramite para estudiantes secundarios.</p></main><footer>Deporte adaptado</footer></html>"""
        self.assertEqual(o.relevancia(o.texto_contenido(pag), {}), [])

    def test_subindice_se_recorre(self):
        sub = b"<html><main>" + b"".join(b'<a href="/b/2021/n%d.pdf">n</a>' % i for i in range(6)) + b"</main></html>"
        idx = b'<html><a href="/boletin-oficial-2021/">2021</a></html>'
        pags = {"https://m.gob.ar/boletin-oficial-2021/": sub,
                **{f"https://m.gob.ar/b/2021/n{i}.pdf": b"<html>deporte adaptado: subsidio al club</html>" for i in range(6)}}
        fdb = FakeDB({"cola_revision": [], "agente_votos": [], "fuente_urls_vistas": []})
        f = {"id": "f1", "url": "https://m.gob.ar/boletin/", "nombre": "B", "tipo": "boletin_oficial", "institucion_id": "i1", "club_id": None}
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(o.time, "sleep"), \
             mock.patch.object(o, "capturar", side_effect=lambda u, **k: cap(u, pags[u])):
            r = o.procesar_indice(f, cap(f["url"], idx), {}, [50], {}, {})
        self.assertEqual(r[0], "subindice"); self.assertEqual(r.count("nuevo"), 5)       # 1 sub-índice + 5 docs (tope 6)
        self.assertFalse(any("boletin-oficial-2021" in c["url_fuente"] for c in fdb.tablas["cola_revision"]))

    def test_reabre_lo_retirado_por_la_limpieza(self):
        c = cap("https://m.gob.ar/d.pdf", b"<html>deporte adaptado</html>")
        fdb = FakeDB({"agente_votos": [], "cola_revision": [
            {"id": "x", "url_fuente": c.url, "hash_sha256": c.sha256, "estado": "rechazada", "revisada_por": "limpieza automática",
             "nota_revision": "Falso positivo del filtro anterior"}]})
        with mock.patch.object(o, "db", return_value=fdb):
            self.assertEqual(o.proponer("rastreador", "documento_nuevo", "t", c, None, "i1", {}), "nuevo")
            self.assertEqual(o.proponer("rastreador", "documento_nuevo", "t", c, None, "i1", {}), "duplicado")
        self.assertEqual(len(fdb.tablas["cola_revision"]), 1)
        self.assertEqual(fdb.tablas["cola_revision"][0]["estado"], "pendiente")
        port = cap("https://m.gob.ar/portada", b"<html>x</html>")
        fdb2 = FakeDB({"agente_votos": [], "cola_revision": [{"id": "p", "url_fuente": port.url, "hash_sha256": port.sha256,
                       "estado": "rechazada", "revisada_por": "limpieza automática", "nota_revision": "Portada de un índice"}]})
        with mock.patch.object(o, "db", return_value=fdb2):
            self.assertEqual(o.proponer("rastreador", "documento_nuevo", "t", port, None, "i1", {}), "duplicado")

    def test_enlaces_que_fallan_cuentan_y_se_anotan(self):
        idx = b"<html>" + b"".join(b'<a href="/d/n%d.pdf">n</a>' % i for i in range(20)) + b"</html>"
        fdb = FakeDB({"cola_revision": [], "agente_votos": [], "fuente_urls_vistas": []})
        f = {"id": "f1", "url": "https://m.gob.ar/i/", "nombre": "I", "tipo": "boletin_oficial", "institucion_id": "i1", "club_id": None}
        pres = [100]
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(o.time, "sleep"), \
             mock.patch.object(o, "capturar", side_effect=lambda u, **k: o.Captura(u, 404, motivo="http_404")):
            r = o.procesar_indice(f, cap(f["url"], idx), {}, pres, {}, {})
        self.assertEqual(r.count("fallo"), o.MAX_NUEVOS_POR_INDICE); self.assertEqual(pres[0], 100 - o.MAX_NUEVOS_POR_INDICE)
        self.assertEqual(len(fdb.tablas["fuente_urls_vistas"]), 1 + o.MAX_NUEVOS_POR_INDICE)

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
