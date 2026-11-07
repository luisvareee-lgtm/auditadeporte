import unittest

import vigia as v
import extractores as ex


class Huecos(unittest.TestCase):
    def test_hueco_largo_si_numero_suelto_no(self):
        ns = [{"juris_slug": "muni-x", "tipo": "decreto", "numero": n, "anio": 2026, "url": f"u{n // 6}"} for n in range(800, 830)
              if n not in (805, 810, 811, 812, 813)]
        a = v.regla_huecos(ns)
        self.assertEqual(len(a), 1)
        self.assertIn("810 a 813", a[0]["explicacion"]["que"])
        self.assertNotIn("805", a[0]["explicacion"]["que"])          # uno suelto puede ser una anulación

    def test_pocos_numeros_no_alcanza(self):
        ns = [{"juris_slug": "muni-x", "tipo": "decreto", "numero": n, "anio": 2026, "url": "u"} for n in (1, 2, 50, 51)]
        self.assertEqual(v.regla_huecos(ns), [])


    def test_una_sola_edicion_no_alcanza(self):
        # caso Jujuy: 33 decretos de una sola edición del boletín, del 29 al 6093 → no es un hueco del boletín
        ns = [{"juris_slug": "prov-jujuy", "tipo": "decreto", "numero": n, "anio": 2026, "url": "133-2026.pdf"}
              for n in [29, 30, 31, 36, 634] + list(range(6064, 6094))]
        self.assertEqual(v.regla_huecos(ns), [])

    def test_norma_segun_jurisdiccion(self):
        self.assertIn("art. 5", v.norma_publicacion("prov-jujuy"))
        self.assertNotIn("14.491", v.norma_publicacion("prov-jujuy"))


class Fraccionamiento(unittest.TestCase):
    U = {"provincia_buenos_aires": {"compra_directa_hasta": 9370451, "concurso_de_precios_hasta": 46855592, "fuente": "Res. 248/2026"}}

    def adj(self, monto, fecha, prov="deportes del sur", mod="compra directa"):
        return {"juris_slug": "muni-x", "proveedor": prov.upper(), "proveedor_n": prov, "monto": monto, "fecha": fecha,
                "modalidad": mod, "url": "u", "pagina": 1, "extracto": "e"}

    def test_tres_compras_directas_que_juntas_superan(self):
        a = v.regla_fraccionamiento([self.adj(9_000_000, "2026-07-01"), self.adj(8_000_000, "2026-07-20"),
                                     self.adj(7_000_000, "2026-08-15")], self.U)
        self.assertEqual(len(a), 1); self.assertEqual(a[0]["gravedad"], "alta")
        self.assertIn("Art. 151", a[0]["explicacion"]["norma"])

    def test_lejos_en_el_tiempo_o_licitacion_no(self):
        self.assertEqual(v.regla_fraccionamiento([self.adj(9_000_000, "2026-01-01"), self.adj(8_000_000, "2026-06-01")], self.U), [])
        self.assertEqual(v.regla_fraccionamiento([self.adj(9_000_000, "2026-07-01", mod="licitacion publica"),
                                                  self.adj(8_000_000, "2026-07-02", mod="licitacion publica")], self.U), [])


class Extractores(unittest.TestCase):
    T = ("DECRETO N° 820\nALMIRANTE BROWN, 16 de Julio de 2026.-\nVISTO: el Decreto N° 123/2020 y\n"
         "ARTICULO 1°.- Adjudícase la Compra Directa N° 45 a la firma DEPORTES DEL SUR S.R.L., CUIT 30-1, por la suma de $ 9.100.000,00.\n")

    def test_normas_solo_encabezados(self):
        self.assertEqual(ex.normas(self.T), [("decreto", 820, 2026)])          # el 123/2020 citado no cuenta

    def test_adjudicacion(self):
        a = ex.adjudicaciones(self.T)[0]
        self.assertEqual((a["proveedor_n"], a["monto"], a["fecha"], a["modalidad"]), ("deportes del sur", 9100000.0, "2026-07-16", "compra directa"))


if __name__ == "__main__":
    unittest.main()


class Ejecuciones(unittest.TestCase):
    def test_credito_y_modificaciones(self):
        import rafam, os
        D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pruebas_rafam")
        es = []
        for n, f in enumerate(["gastos_funcion.txt", "gastos_caracter.txt"]):
            r = rafam.analizar(open(os.path.join(D, f), encoding="utf-8").read())
            es.append({"juris_slug": "muni-almirante-brown", "url": f"u{n}", "sha256": str(n) * 64, **{k: r.get(k) for k in
                       ("tipo", "clasificacion", "ejercicio", "desde", "hasta", "totales", "credito")}})
        c = v.regla_credito(es)
        self.assertEqual(len(c), 2)
        self.assertTrue(any("A instituciones privadas" in a["explicacion"]["que"] and a["gravedad"] == "alta" for a in c))
        m = v.regla_modificaciones(es)
        self.assertEqual(len(m), 1)
        self.assertIn("clasificaciones distintas", m[0]["explicacion"]["que"])
        self.assertIn("4.827.786.439,60", m[0]["titulo"])
