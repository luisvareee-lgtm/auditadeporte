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
                  "Comienza el curso oficial de entrenador. Inscripcion por transferencia al alias de la federacion"]:
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


class Contraste(unittest.TestCase):
    def test_usa_la_ejecucion_anterior_a_la_colecta(self):
        cs = [{"cuenta": "alte.brown1rabsr", "fecha": "2026-07-15", "permalink": "https://www.instagram.com/p/x/"},
              {"cuenta": "otro", "fecha": "2026-07-15", "permalink": "https://www.instagram.com/p/y/"}]
        dep = lambda pct: {"linea": "346 Deporte y recreacion", "vigente": 100.0, "devengado": pct, "pagado": pct, "porcentaje_devengado": pct}
        ej = [{"juris_slug": "muni-almirante-brown", "hasta": "2026-03-31", "deporte": dep(20.0), "url": "u1"},
              {"juris_slug": "muni-almirante-brown", "hasta": "2026-06-30", "deporte": dep(41.0), "url": "u2"},
              {"juris_slug": "muni-almirante-brown", "hasta": "2026-09-30", "deporte": dep(70.0), "url": "u3"}]
        cx = r.contraste(cs, {"alte.brown1rabsr": "muni-almirante-brown"}, ej)
        self.assertEqual(cx["https://www.instagram.com/p/x/"]["hasta"], "2026-06-30")
        self.assertEqual(cx["https://www.instagram.com/p/x/"]["porcentaje_devengado"], 41.0)
        self.assertEqual(cx["https://www.instagram.com/p/x/"]["momento"], "antes")
        self.assertNotIn("https://www.instagram.com/p/y/", cx)
        cx2 = r.contraste([dict(cs[0], fecha="2026-01-10")], {"alte.brown1rabsr": "muni-almirante-brown"}, ej)
        self.assertEqual(cx2["https://www.instagram.com/p/x/"]["momento"], "despues")


class Barrido(unittest.TestCase):
    def test_senales(self):
        self.assertIn("apoyo_estado", r.senales("Gracias al Instituto Municipal del Deporte por los pasajes"))
        self.assertIn("convocatoria_torneo", r.senales("Confirmado el fixture del torneo nacional en Rio Gallegos"))
        self.assertEqual(r.senales("Gracias al municipio por acompanar la cirugia de nuestro jugador"), [])
        self.assertIn("beca_atrasada", r.senales("Seguimos sin cobrar las becas desde marzo"))
        self.assertIn("beca_atrasada", r.senales("Las becas del ENARD estan atrasadas tres meses"))
        import transcribir as tr
        self.assertFalse(tr.conviene({"media_type": "IMAGE", "media_url": "u", "caption": "rifa"}))
        self.assertTrue(tr.conviene({"media_type": "VIDEO", "media_url": "u", "caption": "Necesitamos tu ayuda para viajar"}))
        self.assertIn("promesa_estado", r.senales("Los pasajes que nos iban a dar desde la Secretaria de Deportes no llegaron"))

    def test_barre_todas_las_paginas_y_respeta_presupuesto(self):
        import os, actualidad_redes as ar
        os.environ.setdefault("IG_USER_ID", "1")
        paginas = {None: ("c1", "2026-05-01"), "c1": ("c2", "2020-03-01"), "c2": (None, "2015-01-01")}
        llamadas = []
        def graph(ig, campos):
            cur = campos.split(".after(")[1].split(")")[0] if ".after(" in campos else None
            llamadas.append(cur); sig, f = paginas[cur]
            media = {"data": [{"timestamp": f + "T10:00:00+0000", "permalink": "https://www.instagram.com/p/" + f, "caption": "rifa"}]}
            if sig: media["paging"] = {"cursors": {"after": sig}}
            return {"business_discovery": {"media": media}}
        ar.graph, ar.PAUSA = graph, 0
        posts, completo = r.barrer("faba", "propia", r.DESDE_TOTAL, [10], prueba=True)
        self.assertTrue(completo); self.assertEqual(len(posts), 3); self.assertEqual(llamadas, [None, "c1", "c2"])
        llamadas.clear()
        posts, completo = r.barrer("faba", "propia", r.DESDE_TOTAL, [2], prueba=True)
        self.assertFalse(completo); self.assertEqual(len(posts), 2)


class Contexto(unittest.TestCase):
    """Todo tiene que ser de deporte adaptado / paralímpico / básquet en silla, no palabras sueltas."""
    def test_cuentas_propias_y_generales(self):
        self.assertIsNone(r.contexto_de("basquetadaptadofaba"))
        self.assertIsNone(r.contexto_de("clubxbsr", "Club X"))
        self.assertIsNone(r.contexto_de("clubx", "Club X Básquet Adaptado"))
        self.assertEqual(r.contexto_de("enardinfo", "ENARD"), "enardinfo")
        self.assertEqual(r.contexto_de("prensaensenada", "Municipio de Ensenada"), "prensaensenada")

    def test_enard_deporte_convencional_no_entra(self):
        txt = "Gracias a las empresas que acompañan a nuestros atletas de hockey y remo rumbo al Panamericano. Viajan a Lima."
        self.assertEqual(r.senales(txt, "enardinfo"), [])
        txt2 = "Rifa para el viaje del equipo de vóley al Sudamericano. Bono $2000, transferí al alias."
        self.assertIsNone(r.clasificar(txt2, "2025-05-01", "enardinfo"))

    def test_enard_paralimpico_si_entra(self):
        txt = "La selección de básquet adaptado viaja al Parapanamericano con el apoyo del ENARD. Pasajes y estadía cubiertos."
        self.assertIn("viaje", r.senales(txt, "enardinfo"))

    def test_entrega_de_sillas_sin_deporte_no_entra(self):
        txt = "El municipio realizó la entrega de sillas de ruedas nuevas a vecinos con discapacidad en el centro de salud barrial."
        self.assertEqual(r.senales(txt, "prensaensenada"), [])
        txt2 = "Entrega de sillas de ruedas deportivas nuevas para competir en la liga de alto rendimiento de básquet."
        self.assertIn("equipamiento_nuevo", r.senales(txt2, "prensaensenada"))

    def test_reclamo_suelto_no_entra(self):
        self.assertNotIn("reclamo", r.senales("Hoy se reclamó la ganancia del sorteo del bingo. ¡Felicitaciones!", "basquetadaptadofaba"))
        self.assertNotIn("reclamo", r.senales("Reclamá tu entrada para el show de fin de año.", None))
        self.assertIn("reclamo", r.senales("Reclamamos los pasajes prometidos para el torneo: el plantel no puede viajar.", None))


if __name__ == "__main__":
    unittest.main()
