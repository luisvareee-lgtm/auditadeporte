import unittest

import generar_resumen as g
from prueba_util import FakeDB

CAT = {"jurisdicciones": {
    "muni-a": {"nombre": "Municipalidad de A", "fuentes": [{}]},
    "muni-b": {"nombre": "Municipalidad de B", "fuentes": [], "pendiente": "El sitio municipal pide no ser leído por bots: se cubre con el SIBOM provincial."},
    "muni-c": {"nombre": "Municipalidad de C", "fuentes": [{}]},
    "prov-buenos-aires": {"nombre": "Provincia de Buenos Aires", "fuentes": [{}]}},
    "clubes": {"club-a": ["muni-a", "prov-buenos-aires"], "club-b": ["muni-b", "prov-buenos-aires"], "club-x": ["muni-c", "prov-buenos-aires"]}}
MARCO = {"_fuente": "u", "base_constitucional": "CN", "municipio": {"norma": "ordenanza", "plazo": "razonable", "reclamo": "amparo"},
         "municipio_pba": {"extra": "Ley 14.491"}, "prov-buenos-aires": {"norma": "Ley 12.475", "plazo": "8 días", "reclamo": "x", "alcance": "PE"}}


class T(unittest.TestCase):
    def test_estados_y_conteos(self):
        db = FakeDB({
            "instituciones": [{"id": "ia", "slug": "muni-a", "nombre": "Municipalidad de A"}, {"id": "ib", "slug": "muni-b", "nombre": "Municipalidad de B"},
                              {"id": "ic", "slug": "muni-c", "nombre": "Municipalidad de C"}, {"id": "ip", "slug": "prov-buenos-aires", "nombre": "PBA"}],
            "fuentes_monitoreadas": [
                {"id": "fa", "institucion_id": "ia", "nombre": "Boletín A", "url": "https://a", "tipo": "boletin_oficial", "estado": "activa", "ultimo_status": 200, "ultima_revision": "2026-11-05T06:00"},
                {"id": "fc", "institucion_id": "ic", "nombre": "Compras C", "url": "https://c", "tipo": "compras", "estado": "activa", "ultimo_status": 200},
                {"id": "fp", "institucion_id": "ip", "nombre": "BO PBA", "url": "https://p", "tipo": "boletin_oficial", "estado": "activa", "ultimo_status": 503, "fallos_consecutivos": 3}],
            "fuente_urls_vistas": [{"fuente_id": "fa"}] * 7 + [{"fuente_id": "fc"}] * 2,
            "cola_revision": [{"agente": "rastreador", "estado": "pendiente", "propuesta": {"fuente_id": "fa", "indice": "https://a"}},
                              {"agente": "rastreador", "estado": "rechazada", "revisada_por": "limpieza automática",
                               "propuesta": {"fuente_id": "fa", "indice": "https://a"}}],
            "clubes": [{"id": "ca", "slug": "club-a", "nombre": "Club A"}, {"id": "cb", "slug": "club-b", "nombre": "Club B"},
                       {"id": "cx", "slug": "club-x", "nombre": "Club X", "publicado": False}],
            "documentos_fuente": [{"club_id": "ca", "publicado": True, "titulo": "Decreto 1500", "url_fuente": "https://a/d.pdf",
                                   "temas": ["juegos_bonaerenses"], "fecha_captura": "2026-08-03T10:00",
                                   "capturas": [{"url": "https://x.supabase.co/storage/v1/object/public/capturas-publicas/h/pagina-2.jpg", "pagina": 2},
                                                {"url": "javascript:alert(1)", "pagina": 3}]},
                                  {"club_id": "ca", "publicado": False}],
            "ejecuciones_presupuestarias": [
                {"juris_slug": "muni-a", "url": "https://a/ejec.pdf", "tipo": "gastos", "clasificacion": "finalidad_funcion", "ejercicio": 2026,
                 "desde": "2026-01-02", "hasta": "2026-03-31", "publicado": True,
                 "deporte": {"linea": "346 Deporte y recreación", "vigente": 426616020.17, "devengado": 70603099.95, "pagado": 70603099.95, "porcentaje_devengado": 16.5}},
                {"juris_slug": "muni-a", "url": "https://a/otro.pdf", "tipo": "gastos", "publicado": False,
                 "deporte": {"linea": "346", "vigente": 1, "devengado": 1}}]})
        r = g.construir(db, CAT, MARCO)
        j = {x["slug"]: x for x in r["jurisdicciones"]}
        self.assertEqual(j["muni-a"]["estado"], "publica")
        self.assertEqual((j["muni-a"]["documentos_leidos"], j["muni-a"]["encontrados_para_revisar"], j["muni-a"]["publicados"]), (7, 1, 1))
        self.assertEqual(j["muni-b"]["estado"], "no_publica"); self.assertIn("SIBOM", j["muni-b"]["motivo"])
        self.assertEqual(j["muni-c"]["estado"], "a_medias")
        self.assertEqual(j["muni-c"]["clubes"], [])                                  # club despublicado: no figura
        self.assertEqual(j["prov-buenos-aires"]["estado"], "no_publica")             # su fuente no respondió
        self.assertEqual(j["muni-a"]["pedido"]["extra"], "Ley 14.491")
        self.assertEqual([x["porcentaje_devengado"] for x in j["muni-a"]["presupuesto_deporte"]], [16.5])   # solo lo publicado
        jb = j["muni-a"]["juegos_bonaerenses"]
        self.assertEqual(len(jb["publicados"]), 1)
        self.assertEqual([c["pagina"] for c in jb["publicados"][0]["capturas"]], [2])          # solo enlaces https
        self.assertIsNone(j["prov-buenos-aires"]["juegos_bonaerenses"])                       # el apartado es municipal
        self.assertEqual(j["muni-a"]["documentos"][0]["titulo"], "Decreto 1500")
        ck = {i["clave"]: i["estado"] for i in j["muni-a"]["checklist"]}
        self.assertEqual(ck, {"boletin": "completo", "compras": "no_encontrado", "presupuesto": "no_encontrado",
                              "normas": "no_encontrado", "deporte_adaptado": "completo"})
        ckp = {i["clave"]: i["estado"] for i in j["prov-buenos-aires"]["checklist"]}
        self.assertNotIn("normas", ckp)                                              # el Concejo es solo municipal
        self.assertEqual(ckp["boletin"], "parcial")                                  # existe pero no respondió
        self.assertEqual({i["clave"]: i["estado"] for i in j["muni-b"]["checklist"]}["boletin"], "no_encontrado")
        self.assertIn("Ley 12.475", j["muni-a"]["pedido"]["provincial"])
        self.assertEqual(r["totales"]["no_publica"], 2)
        texto = str(r).lower()
        for palabra in ("corrup", "oculta", "esconde", "irregular"):
            self.assertNotIn(palabra, texto)


if __name__ == "__main__":
    unittest.main()
