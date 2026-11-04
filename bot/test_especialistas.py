import base64
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import especialistas as e
import orquestador_bots_audita as o
from prueba_util import FakeDB

PRIVADAS_OK = {"cola_revision", "agente_votos", "agente_ejecuciones"}


def jwt(rol):
    def b(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'HS256', 'typ': 'JWT'})}.{b({'iss': 'supabase', 'role': rol, 'ref': 'abcdefghij'})}.firmaFalsaParaTest123"


class T(unittest.TestCase):
    def correr(self, fdb, fn, *a, **k):
        with mock.patch.object(o, "db", return_value=fdb):
            return fn(*a, **k)

    def test_rse_propone_borrador_una_sola_vez(self):
        fdb = FakeDB({"novedades_redes": [{"id": "n1", "club_id": "c1", "url_publicacion": "https://www.instagram.com/p/1/",
                                           "fecha_posteo": "2026-10-25", "extracto": "Rifa para el viaje al torneo", "publicado": True,
                                           "menciona_colecta": True}],
                      "clubes": [{"id": "c1", "nombre": "Club Uno"}], "pliegos_rse": []})
        r = self.correr(fdb, e.analista_rse, hoy=date(2026, 11, 3))
        self.assertEqual(r, ["nuevo"])
        p = fdb.tablas["cola_revision"][0]
        self.assertEqual(p["propuesta"]["accion"], "borrador_pliego_rse")
        self.assertEqual(p["propuesta"]["parametros"]["rubro"], "traslado")
        self.assertEqual(p["estado"], "pendiente")
        self.assertEqual(self.correr(fdb, e.analista_rse, hoy=date(2026, 11, 3)), ["duplicado"])
        self.assertTrue(fdb.escrituras() <= PRIVADAS_OK, fdb.escrituras())

    def test_rse_no_duplica_si_ya_hay_pliego_abierto(self):
        fdb = FakeDB({"novedades_redes": [{"id": "n1", "club_id": "c1", "url_publicacion": "https://x.org/p", "fecha_posteo": "2026-10-25",
                                           "extracto": "Rifa para comprar sillas", "publicado": True, "menciona_colecta": True}],
                      "clubes": [{"id": "c1", "nombre": "Club Uno"}],
                      "pliegos_rse": [{"club_id": "c1", "rubro": "equipamiento", "estado": "abierto"}]})
        self.assertEqual(self.correr(fdb, e.analista_rse, hoy=date(2026, 11, 3)), [])

    def test_reclamo_de_pedido_vencido(self):
        fdb = FakeDB({"v_pedidos_vencidos": [{"id": "p1", "organismo": "Municipio X", "ambito": "municipal", "asunto": "Subsidios 2026",
                                              "fecha_envio": "2026-09-01", "fecha_limite": "2026-09-22", "dias_de_atraso": 42}]})
        self.assertEqual(self.correr(fdb, e.seguimiento_pedidos), ["nuevo"])
        p = fdb.tablas["cola_revision"][0]["propuesta"]
        self.assertEqual(p["accion"], "reclamar_pedido"); self.assertIn("Municipio X", p["borrador_texto"])
        self.assertNotIn("27.275", p["borrador_texto"])          # ley nacional solo si el ámbito es nacional

    def test_vigencia_detecta_nombre_ausente(self):
        pagina = ("<html><body>" + "Comisión directiva 2026 " * 30 + "Presidenta: Ana Gómez</body></html>").encode()
        fdb = FakeDB({"autoridades": [
            {"id": "a1", "nombre": "Ana Gómez", "cargo": "Presidencia", "fuente_url": "https://x.org.ar/aut", "publicable": True, "vigente": True, "institucion_id": "i1"},
            {"id": "a2", "nombre": "Luis Pérez", "cargo": "Tesorería", "fuente_url": "https://x.org.ar/aut", "publicable": True, "vigente": True, "institucion_id": "i1"}],
            "v_hechos_vencidos": []})
        with mock.patch.object(o, "capturar", return_value=o.Captura("https://x.org.ar/aut", 200, pagina, "b" * 64)), \
             mock.patch.object(o.time, "sleep"):
            r = self.correr(fdb, e.control_vigencia)
        self.assertEqual(r, ["nuevo"])
        p = fdb.tablas["cola_revision"][0]
        self.assertEqual(p["propuesta"]["parametros"]["autoridad_id"], "a2")

    def test_vigencia_no_infiere_de_paginas_vacias(self):
        fdb = FakeDB({"autoridades": [{"id": "a1", "nombre": "Ana Gómez", "cargo": "P", "fuente_url": "https://x.org.ar/aut",
                                       "publicable": True, "vigente": True, "institucion_id": "i1"}], "v_hechos_vencidos": []})
        with mock.patch.object(o, "capturar", return_value=o.Captura("https://x.org.ar/aut", 200, b"<div id=app></div>", "b" * 64)), \
             mock.patch.object(o.time, "sleep"):
            self.assertEqual(self.correr(fdb, e.control_vigencia), [])

    def test_delegado_datos_cuenta_sin_copiar_contactos(self):
        fdb = FakeDB({"tips": [{"id": 1, "estado": "descartado", "creado_en": "2026-01-01", "contacto": "secreto@mail.com"},
                               {"id": 2, "estado": "nuevo", "creado_en": "2026-01-01", "contacto": "otro@mail.com"}],
                      "presentaciones_club": [], "postulaciones_rse": [], "cola_revision": []})
        self.assertEqual(self.correr(fdb, e.delegado_datos, hoy=date(2026, 11, 3)), ["nuevo"])
        fila = fdb.tablas["cola_revision"][0]
        self.assertIn("Borrar 1 contacto", fila["titulo"])
        self.assertNotIn("secreto@mail.com", json.dumps(fila))
        self.assertEqual(self.correr(fdb, e.delegado_datos, hoy=date(2026, 11, 3)), [])      # ya hay una pendiente

    def test_cruces(self):
        fdb = FakeDB({"v_cruces_expediente": [{"expediente": "EX-1", "fuentes": 2, "urls": ["https://b.gob.ar/2", "https://a.gob.ar/1"]}]})
        self.assertEqual(self.correr(fdb, e.analista_cruces), ["nuevo"])
        self.assertEqual(fdb.tablas["cola_revision"][0]["url_fuente"], "https://a.gob.ar/1")

    def test_guardian_detecta_service_role_en_repo_sin_copiar_la_clave(self):
        with tempfile.TemporaryDirectory() as d:
            clave = jwt("service_role")
            Path(d, ".github").mkdir()
            Path(d, ".github", "crawlers.yml").write_text(f'KEY: "{clave}"\n')
            Path(d, "index.html").write_text(f'anon: "{jwt("anon")}"')
            fdb = FakeDB()
            with mock.patch.object(e, "_get", return_value=(0, {}, b"")):
                r, critico = self.correr(fdb, e.guardian_seguridad, raiz_repo=d)
        self.assertTrue(critico); self.assertEqual(r, ["nuevo"])
        fila = fdb.tablas["cola_revision"][0]
        self.assertIn("crawlers.yml:1", json.dumps(fila, ensure_ascii=False))
        self.assertNotIn(clave, json.dumps(fila))

    def test_guardian_cabeceras_y_rls(self):
        def falso_get(url, cab=None, metodo="GET", cuerpo=None):
            if "/rest/v1/tips" in url:
                return 200, {}, b'[{"id":1}]'                   # simulamos una tabla privada expuesta
            if "/rest/v1/" in url:
                return 401, {}, b""
            return 200, {"content-security-policy": "x"}, b"<html>ok</html>"
        fdb = FakeDB()
        with mock.patch.object(e, "_get", side_effect=falso_get):
            r, critico = self.correr(fdb, e.guardian_seguridad, raiz_repo=None, url_supabase="https://p.supabase.co",
                                     clave_publica="sb_publishable_abc")
        self.assertTrue(critico)
        titulos = [f["titulo"] for f in fdb.tablas["cola_revision"]]
        self.assertTrue(any("cabeceras" in t for t in titulos)); self.assertTrue(any("privados" in t for t in titulos))

    def test_main_no_se_cae_si_un_especialista_falla(self):
        fdb = FakeDB()
        with mock.patch.object(o, "db", return_value=fdb), \
             mock.patch.object(e, "ESPECIALISTAS", [lambda: 1 / 0]), \
             mock.patch.object(e, "guardian_seguridad", return_value=([], False)):
            e.main()
        self.assertEqual(fdb.tablas["agente_ejecuciones"][0]["errores"], 1)


if __name__ == "__main__":
    unittest.main()
