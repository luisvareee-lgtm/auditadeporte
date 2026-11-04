import unittest
from unittest import mock

import orquestador_bots_audita as o
import relevar_faba as r
from prueba_util import FakeDB

LISTADO_1 = b"""<html><body><main>
<a href="https://basquetadaptado.com.ar/clubes/cedima/">CEDIMA</a>
<a href="/clubes/crol/">CROL</a>
<a href="https://basquetadaptado.com.ar/clubes/page/2/">2</a>
<a href="https://basquetadaptado.com.ar/autoridades/">Autoridades</a>
</main></body></html>"""
LISTADO_2 = b"""<html><body><a href="https://basquetadaptado.com.ar/clubes/club-nuevo-sur/">Nuevo</a>
<a href="https://basquetadaptado.com.ar/clubes/">1</a></body></html>"""

HOY = r.ahora().date().isoformat()
FICHA_A = ("""<html><head><meta property="og:title" content="CEDIMA &#8211; FABA">
<meta property="article:modified_time" content="%sT10:00:00+00:00" /></head><body>""" % HOY + """
<header><a>Menú</a> Presidente: Persona Del Menu</header><main>
<h1>CEDIMA</h1>
<p><strong>Localidad:</strong> Caseros</p><p>Provincia: Buenos Aires</p>
<p>Presidente: Juan Carlos Pérez</p>
<p>Tesorera - MARÍA GÓMEZ</p>
<p>Ana Ruiz (Secretaria)</p>
<p>Delegado: Raúl Díaz Tel. 11 4444-5555 raul@mail.com</p>
<p>Mandato 2021-2023</p>
<table><tr><td>Vocal 1°</td><td>Luis Fernández</td></tr></table>
<p>Contacto: 011 4444-5555</p>
<p>Instagram</p><p>@club_ce.di.ma</p><p>Facebook</p><p>CEDIMA Oficial</p>
<a href="https://www.instagram.com/basquetadaptadofaba/">FABA</a>
<a href="https://www.facebook.com/sharer/sharer.php?u=x">Compartir</a>
<p>Jugadores de Selección</p><p>Presidente: Nombre Que No Va</p><p>Fecha de Nacimiento</p><p>20/08/2010</p>
</main></body></html>""").encode()
FICHA_VIEJA = b"""<html><head><meta property="article:modified_time" content="2022-04-29T12:07:34+00:00" /></head><body><main>
<h1>Almirante Brown</h1><p>Presidente</p><p>FRISA JONATHAN</p><p>Instagram</p><p>@deporteinclusivobrown</p>
<p>Planillas de juego</p><p>MUNIC.ALTE. BROWN 2019 CONTROL</p></main></body></html>"""
FICHA_B = b"<html><body><main><h1>Club Nuevo Sur</h1><p>Presidente: Pedro Sosa</p></main></body></html>"
FICHA_C = b"<html><body><main><h1>CROL</h1><p>Sin datos</p></main></body></html>"


def cap(url, data):
    import hashlib
    return o.Captura(url, 200, data, hashlib.sha256(data).hexdigest()), {"ETag": '"abc"'}


class T(unittest.TestCase):
    def test_tacha_contactos_pero_no_mandatos(self):
        t = r.tachar("Tel 11 4444-5555, mail a@b.com, DNI 30.123.456, mandato 2021-2023")
        self.assertNotIn("4444", t); self.assertNotIn("a@b.com", t); self.assertNotIn("30.123.456", t)
        self.assertIn("2021-2023", t)

    def test_extrae_autoridades_en_varios_formatos(self):
        ls = [r.tachar(x) for x in r.lineas(FICHA_A)]
        aut = {(a["cargo"], a["nombre"]) for a in r.extraer_autoridades(ls)}
        self.assertIn(("Presidente", "Juan Carlos Pérez"), aut)
        self.assertIn(("Tesorera", "María Gómez"), aut)
        self.assertIn(("Secretaria", "Ana Ruiz"), aut)
        self.assertIn(("Vocal 1°", "Luis Fernández"), aut)
        self.assertNotIn("Persona Del Menu", {n for _, n in aut})       # el encabezado no cuenta
        self.assertIn(("Delegado", "Raúl Díaz"), aut)                    # se queda el nombre, el contacto no
        self.assertEqual(r.extraer_datos(ls).get("localidad"), "Caseros")
        self.assertEqual(r.titulo_pagina(FICHA_A), "CEDIMA")
        self.assertNotIn("Nombre Que No Va", {n for _, n in aut})       # sección de jugadores: no se procesa
        self.assertFalse(any("2010" in l for l in ls))
        redes = r.extraer_redes(ls, FICHA_A)
        self.assertEqual(redes.get("instagram"), "club_ce.di.ma")          # la cuenta de FABA no cuenta
        self.assertNotIn("facebook", redes)                                 # "CEDIMA Oficial" no es un enlace
        self.assertEqual(redes["texto_publicado"]["facebook"], "CEDIMA Oficial")

    def test_nombre_valido_rechaza_basura(self):
        for malo in ("Comisión Directiva", "Ver más", "Juan", "Calle 123 Nro 4", "[correo omitido] Juan Pérez"):
            self.assertIsNone(r.nombre_valido(malo), malo)
        self.assertEqual(r.nombre_valido("Dra. Laura de la Fuente"), "Laura de la Fuente")

    def test_listado_y_paginacion(self):
        f, p = r.urls_fichas(LISTADO_1, r.LISTADO)
        self.assertEqual(f, ["https://basquetadaptado.com.ar/clubes/cedima/", "https://basquetadaptado.com.ar/clubes/crol/"])
        self.assertEqual(p, ["https://basquetadaptado.com.ar/clubes/page/2/"])

    def test_emparejar(self):
        clubes = [{"id": "1", "slug": "cedima", "nombre": "CEDIMA"}, {"id": "2", "slug": "crol", "nombre": "Club Rosarino CROL"}]
        self.assertEqual(r.emparejar("cedima", "x", clubes)[1], "slug")
        self.assertIsNone(r.emparejar("club-nuevo-sur", "Club Nuevo Sur", clubes)[0])
        base = [{"id": s, "slug": s, "nombre": n} for s, n in [
            ("cripal", "CRIPAL"), ("cef-n-17", "CEF N° 17"), ("prodea", "PRODEA"), ("cilsa-santa-fe", "CILSA Santa Fe"),
            ("cilsa-boca-juniors", "CILSA Boca Juniors"), ("municipalidad-de-ensenada", "Municipalidad de Ensenada"),
            ("municipalidad-de-berazategui", "Municipalidad de Berazategui"), ("sica-poeta-lugones", "SICA / Poeta Lugones")]]
        casos = {"c-ri-pa-l-centro-rionegrino-para-lisiados-deportistas": "cripal",
                 "asociacion-cooperadora-cef-17": "cef-n-17", "prodea-las-aguilas": "prodea",
                 "c-i-l-s-a-centro-integracion-libre-y-solidaria-de-argentina-sede-santa": "cilsa-santa-fe",
                 "cilsa-buenos-aires": None, "municipalidad-de-escobar": None,
                 "club-social-y-deportivo-poeta-lugones": None}
        for faba, esperado in casos.items():
            self.assertEqual((r.emparejar(faba, faba.replace("-", " "), base)[0] or {}).get("slug"), esperado, faba)

    def test_ciclo_completo_propone_sin_publicar(self):
        paginas = {r.LISTADO: LISTADO_1, "https://basquetadaptado.com.ar/clubes/page/2/": LISTADO_2,
                   "https://basquetadaptado.com.ar/clubes/cedima/": FICHA_A,
                   "https://basquetadaptado.com.ar/clubes/crol/": FICHA_C,
                   "https://basquetadaptado.com.ar/clubes/club-nuevo-sur/": FICHA_B}
        fdb = FakeDB({"clubes": [{"id": "c1", "slug": "cedima", "nombre": "CEDIMA"}, {"id": "c2", "slug": "crol", "nombre": "CROL"}],
                      "instituciones": [{"id": "i1", "slug": "faba", "sigla": "FABA"}],
                      "autoridades": [{"id": "a1", "club_id": "c1", "institucion_id": None, "nombre": "Juan Carlos Pérez",
                                       "cargo": "Presidente", "vigente": True},
                                      {"id": "a2", "club_id": "c1", "institucion_id": None, "nombre": "Ex Tesorero Viejo",
                                       "cargo": "Tesorero", "vigente": True},
                                      {"id": "a3", "club_id": None, "institucion_id": "i1", "nombre": "Ana Ruiz",
                                       "cargo": "Secretaria", "vigente": True}],
                      "cola_revision": [], "agente_votos": []})
        with mock.patch.object(r, "capturar", side_effect=lambda u, timeout=25: cap(u, paginas[u])), \
             mock.patch.object(r, "PAUSA_SEG", 0), mock.patch.object(r.time, "sleep"), \
             mock.patch.object(o, "db", return_value=fdb), mock.patch.object(r, "db", return_value=fdb):
            clubes, _ = r.relevar()
            cont = r.proponer_en_cola(clubes)
            cont2 = r.proponer_en_cola(clubes)                          # segunda corrida: todo duplicado
        cola = fdb.tablas["cola_revision"]
        tipos = [(c["tipo"], (c["propuesta"].get("accion"))) for c in cola]
        # Presidente ya cargado -> no se repite; Tesorera, Secretaria, Delegado y Vocal -> autoridad_posible
        self.assertEqual(cont["autoridad_posible"], 4)
        self.assertEqual(cont["no_figura"], 1)                          # "Ex Tesorero Viejo" ya no figura
        self.assertEqual(cont["club_no_registrado"], 1)                 # Club Nuevo Sur
        self.assertEqual(cont["cruce"], 1)                              # Ana Ruiz: club CEDIMA + FABA
        self.assertEqual(cont2.get("duplicado"), len(cola))
        self.assertTrue(all(c["estado"] in ("pendiente", "bloqueada_legal") for c in cola))
        self.assertTrue(all("#" in c["url_fuente"] for c in cola if c["tipo"] == "autoridad_posible"))
        self.assertIn(("propuesta_cambio", "marcar_no_vigente"), tipos)
        # nada se escribió en tablas públicas
        self.assertFalse(fdb.escrituras() & {"autoridades", "clubes", "instituciones"})
        # ningún contacto llegó a la cola
        self.assertNotIn("4444", str(cola)); self.assertNotIn("@mail", str(cola))

    def test_ficha_vencida_no_propone_autoridades_y_retira_pendientes(self):
        u = "https://basquetadaptado.com.ar/clubes/almirante-brown/"
        paginas = {r.LISTADO: b'<a href="/clubes/almirante-brown/">x</a>', u: FICHA_VIEJA}
        fdb = FakeDB({"clubes": [{"id": "b1", "slug": "almirante-brown", "nombre": "Almirante Brown", "instagram": None}],
                      "instituciones": [{"id": "i1", "slug": "faba"}], "autoridades": [], "agente_votos": [],
                      "cola_revision": [{"id": "viejo", "agente": r.AGENTE, "tipo": "autoridad_posible", "estado": "pendiente",
                                         "club_id": "b1", "url_fuente": u + "#x", "hash_sha256": "f" * 64},
                                        {"id": "nofig", "agente": r.AGENTE, "tipo": "propuesta_cambio", "estado": "pendiente",
                                         "club_id": "b1", "propuesta": {"accion": "marcar_no_vigente"}},
                                        {"id": "redmal", "agente": r.AGENTE, "tipo": "propuesta_cambio", "estado": "pendiente",
                                         "club_id": "b1", "propuesta": {"accion": "actualizar_redes_club",
                                                                         "parametros": {"facebook": "https://www.facebook.com/sharer/sharer.php"}}}]})
        with mock.patch.object(r, "capturar", side_effect=lambda x, timeout=25: cap(x, paginas[x])), \
             mock.patch.object(r.time, "sleep"), mock.patch.object(o, "db", return_value=fdb), mock.patch.object(r, "db", return_value=fdb):
            clubes, _ = r.relevar()
            cont = r.proponer_en_cola(clubes)
        self.assertFalse(clubes[0]["vigente"]); self.assertEqual(clubes[0]["anios_planillas"], [2019])
        self.assertEqual(cont["autoridad_posible"], 0)
        self.assertEqual(cont["descartadas_por_antiguedad"], 2)
        viejo = next(c for c in fdb.tablas["cola_revision"] if c["id"] == "viejo")
        self.assertEqual((viejo["estado"], viejo["motivo_codigo"]), ("rechazada", "desactualizado"))
        redes = [c for c in fdb.tablas["cola_revision"] if c.get("propuesta", {}).get("accion") == "actualizar_redes_club" and c["estado"] == "pendiente"]
        self.assertEqual(redes[0]["propuesta"]["parametros"], {"instagram": "deporteinclusivobrown"})
        self.assertEqual(cont.get("padron"), 1)
        mal = next(c for c in fdb.tablas["cola_revision"] if c["id"] == "redmal")
        self.assertEqual(mal["estado"], "rechazada"); self.assertEqual(cont["redes_retiradas"], 1)                             # hallazgo: padrón sin actualizar

    def test_bloqueo_detiene(self):
        with mock.patch.object(r, "capturar", return_value=(o.Captura(r.LISTADO, 403, motivo="http_403"), {})), \
             mock.patch.object(r.time, "sleep"):
            with self.assertRaises(SystemExit):
                r.relevar()


if __name__ == "__main__":
    unittest.main()
