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


class TiposYPatrones(unittest.TestCase):
    def test_tipos_destinatario_y_limite(self):
        c = r.clasificar("Rifa y venta de empanadas para viajar al Nacional. Buscamos sponsors. Necesitamos juntarlo antes del 5 de junio",
                         "2026-05-20")
        self.assertIn("rifa_sorteo", c["tipos_pedido"]); self.assertIn("venta_comida", c["tipos_pedido"])
        self.assertIn("pedido_empresas", c["tipos_pedido"]); self.assertIn("empresas", c["destinatarios"])
        self.assertEqual(c["fecha_limite"], "2026-06-05")

    def test_no_son_colectas(self):
        for t in ["Mundial Dubai 2023: se sorteo la fase de grupos. Argentina en la zona A con Canada",
                  "Sorteo: ganate una pelota oficial, participa del sorteo siguiendo la cuenta",
                  "Comienza el curso oficial de entrenador. Inscripcion por transferencia"]:
            self.assertIsNone(r.clasificar(t, "2023-02-08"), t)
        self.assertIsNotNone(r.clasificar("Rifa solidaria para viajar al Nacional: numeros a $2000, alias en bio", "2023-02-08"))

    def test_patrones_agrupa_parecidas(self):
        import patrones_colectas as pc
        base = {"tipos_pedido": ["rifa_sorteo"], "torneos": ["liga_nacional"], "montos": [], "destinatarios": ["personas"]}
        cs = [dict(base, cuenta="a", fecha="2026-04-10", finalidades=["viaje_torneo"]),
              dict(base, cuenta="b", fecha="2026-04-20", finalidades=["viaje_torneo"]),
              dict(base, cuenta="c", fecha="2026-04-25", finalidades=["viaje_torneo"], montos=[{"moneda": "ARS", "valor": 500000.0}]),
              {"cuenta": "d", "fecha": "2025-09-01", "finalidades": ["silla_equipamiento"], "tipos_pedido": ["transferencia"],
               "torneos": [], "montos": [], "destinatarios": ["personas"]}]
        ps = pc.patrones(cs)
        self.assertEqual(ps[0]["colectas"], 3); self.assertEqual(ps[0]["cuentas"], 3)
        self.assertEqual(ps[0]["necesidad"], "viajes a torneos"); self.assertEqual(ps[0]["rse"], "alta")
        self.assertEqual(ps[0]["montos"]["ARS"]["mayor"], 500000.0)
        self.assertEqual(len(ps), 2)


if __name__ == "__main__":
    unittest.main()
