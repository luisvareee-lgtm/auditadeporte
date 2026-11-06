"""Pruebas con líneas reales de los reportes RAFAM de Almirante Brown (1er y 2do trimestre 2026, públicos)."""
import os
import unittest

import rafam

AQUI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pruebas_rafam")


class Rafam(unittest.TestCase):
    def test_funcion_y_deporte(self):
        r = rafam.analizar(open(os.path.join(AQUI, "gastos_funcion.txt"), encoding="utf-8").read())
        self.assertEqual((r["tipo"], r["clasificacion"], r["desde"], r["hasta"]), ("gastos", "finalidad_funcion", "2026-01-02", "2026-03-31"))
        d = r["deporte"]
        self.assertEqual((d["aprobado"], d["devengado"], d["pagado"], d["porcentaje_devengado"]), (426410500.0, 70603099.95, 70603099.95, 16.5))
        self.assertAlmostEqual(d["peso_en_presupuesto"], 0.152)
        self.assertEqual(r["cierre"], [])
        self.assertEqual(r["credito"][0]["linea"], "420 Comunicaciones")
        self.assertAlmostEqual(r["credito"][0]["exceso"], 405195642.58, places=2)

    def test_caracter_economico_y_numeros_pegados(self):
        r = rafam.analizar(open(os.path.join(AQUI, "gastos_caracter.txt"), encoding="utf-8").read())
        self.assertEqual((r["clasificacion"], r["hasta"]), ("caracter_economico", "2026-06-30"))
        self.assertIsNone(r["deporte"])                           # por carácter económico no hay función deporte
        self.assertEqual(r["totales"]["vigente"], 289272356639.17)  # la fila de totales trae números pegados
        self.assertAlmostEqual(r["credito"][0]["exceso"], 16946411806.05, places=2)

    def test_no_es_rafam(self):
        self.assertIsNone(rafam.analizar("Decreto 820. Visto el expediente..."))

    def test_formatos_mezclados(self):
        self.assertEqual(rafam.NUM.findall("x 51,546,702.22 y 1.234,56 y 17.2.01.51 y 0.00"), ["51,546,702.22", "1.234,56", "0.00"])


if __name__ == "__main__":
    unittest.main()
