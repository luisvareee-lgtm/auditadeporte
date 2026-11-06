import unittest

import relevar_colectas as r


class Clasificar(unittest.TestCase):
    def test_colecta_de_viaje_con_monto_y_torneo(self):
        c = r.clasificar("¡Necesitamos juntar USD 20.000 para los pasajes al Repechaje del Mundial! Alias: somoslas…")
        self.assertEqual(c["finalidades"], ["viaje_torneo"])
        self.assertEqual(set(c["torneos"]), {"mundial", "repechaje"})
        self.assertEqual(c["montos"], [{"moneda": "USD", "valor": 20000.0}])

    def test_rifa_para_sillas_y_pesos_en_millones(self):
        c = r.clasificar("Rifa a beneficio: cubiertas y repuestos para las sillas del plantel. Meta $ 1.500.000")
        self.assertIn("silla_equipamiento", c["finalidades"])
        self.assertEqual(c["montos"], [{"moneda": "ARS", "valor": 1500000.0}])

    def test_no_colecta_y_salud_se_descartan(self):
        self.assertIsNone(r.clasificar("Gran triunfo ante Ferro en la Liga Nacional"))
        self.assertIsNone(r.clasificar("Colecta para la operación de un compañero"))        # salud de una persona: no se releva

    def test_agregado(self):
        filas = [{"cuenta": "a", "nombre_cuenta": "A", "tipo_cuenta": "club", "fecha": "2026-05-01", "permalink": "p1",
                  "finalidades": ["viaje_torneo"], "torneos": ["liga_nacional"], "montos": [{"moneda": "ARS", "valor": 100000.0}]},
                 {"cuenta": "a", "nombre_cuenta": "A", "tipo_cuenta": "club", "fecha": "2025-03-01", "permalink": "p2",
                  "finalidades": ["general"], "torneos": [], "montos": []}]
        a = r.agregar(filas)
        self.assertEqual(a["por_anio"], {"2025": 1, "2026": 1})
        self.assertEqual(a["por_cuenta"]["A"]["colectas"], 2)
        self.assertEqual(a["montos_declarados"]["ARS"], {"cantidad": 1, "mayor": 100000.0})


if __name__ == "__main__":
    unittest.main()
