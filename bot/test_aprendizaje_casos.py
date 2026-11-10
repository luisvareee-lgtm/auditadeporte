import unittest

import aprendizaje_casos as ac
import relevar_colectas as rc


def fila(link, cuenta, tipo, texto, decision=None):
    h = rc.huella(texto)
    return {"permalink": link, "cuenta": cuenta, "tipo_cuenta": tipo, "fecha": "2026-05-01", "terminos": h["t"],
            "huella": {"s": h["s"], **({"c": h["c"]} if "c" in h else {})}, "decision": decision}


BUENOS = ["Viajamos a la Liga Nacional de básquet adaptado, gracias al municipio por los pasajes.",
          "Entrega de sillas deportivas nuevas para el plantel de básquet sobre silla de ruedas, rumbo al cuadrangular.",
          "Reclamamos los pasajes prometidos para el torneo: el plantel de básquet adaptado no puede viajar."]
MALOS = ["Entrega de sillas de ruedas a vecinos en el hospital municipal. Acto con el intendente.",
         "Las Leonas viajan a Chile: gracias a las empresas que acompañan al hockey argentino.",
         "Reclamá tu entrada para el show del festival de fin de año, hay sorteos y premios."]


class Huella(unittest.TestCase):
    def test_no_guarda_texto_ni_palabras_fuera_del_diccionario(self):
        h = rc.huella("Juan Pérez, DNI 30111222, viajamos a Río Gallegos con el alias club.brown para el torneo de básquet adaptado")
        self.assertTrue(set(h["t"]) <= set(rc.DICCIONARIO))
        todo = str(h).lower()
        for prohibido in ("juan", "perez", "30111222", "club.brown", "gallegos"):
            self.assertNotIn(prohibido, todo)

    def test_salud_no_deja_huella(self):
        self.assertIsNone(rc.huella("Colecta para la operación de un jugador, alias tal"))

    def test_la_huella_decide_igual_que_el_texto(self):
        for t in BUENOS + MALOS:
            for cuenta in (None, "enardinfo"):
                h = rc.huella(t)
                self.assertEqual(rc.senales_de(h, cuenta is None), rc.senales(t, cuenta))


class Aprendizaje(unittest.TestCase):
    def modelo(self):
        casos = []
        for i in range(5):
            casos += [fila(f"b{i}{j}", "clubx", "club", t, "aprobado") for j, t in enumerate(BUENOS)]
            casos += [fila(f"m{i}{j}", "prensax", "institucion", t, "descartado") for j, t in enumerate(MALOS)]
        return ac.entrenar(casos)

    def test_con_pocos_casos_no_puntua(self):
        mod = ac.entrenar([fila("a", "clubx", "club", BUENOS[0], "aprobado")])
        self.assertFalse(ac.listo(mod))
        self.assertIsNone(ac.puntaje(fila("z", "clubx", "club", BUENOS[1]), mod))

    def test_ordena_lo_parecido_a_lo_aprobado_arriba(self):
        mod = self.modelo()
        self.assertTrue(ac.listo(mod))
        alto = ac.puntaje(fila("n1", "otroclub", "club", "Viajamos al torneo de básquet adaptado, el municipio pagó los pasajes"), mod)
        bajo = ac.puntaje(fila("n2", "otraprensa", "institucion", "Entrega de sillas de ruedas en el hospital, acto con vecinos"), mod)
        self.assertGreater(alto, 70); self.assertLess(bajo, 30)

    def test_pesos_legibles_y_sin_cuentas(self):
        w = ac.pesos(self.modelo(), 60)
        self.assertTrue(all(not k.startswith("cuenta:") for _, k, _, _ in w))
        self.assertIn("t:hospital", [k for p, k, _, _ in w if p < 0])

    def test_reevaluar_sin_releer(self):
        mem = [fila("p1", "enardinfo", "institucion", MALOS[1]), fila("p2", "enardinfo", "institucion", BUENOS[0]),
               fila("p3", "clubbsr", "club", "Rifa para los pasajes al torneo, bono $2000, alias del club"),
               fila("p4", "clubbsr", "club", BUENOS[2], "descartado")]
        r = ac.reevaluar(mem, {})
        self.assertEqual(set(r["senales"]), {"p2"})
        self.assertEqual(r["colectas"], {"p3"})


if __name__ == "__main__":
    unittest.main()
