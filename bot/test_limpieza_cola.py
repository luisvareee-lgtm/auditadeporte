import unittest
from unittest import mock

import limpieza_cola as l
import orquestador_bots_audita as o
from prueba_util import FakeDB


class T(unittest.TestCase):
    def test_limpieza(self):
        cola = [
            {"id": "1", "agente": "rastreador", "tipo": "documento_nuevo", "titulo": "Boletín PBA", "estado": "pendiente",
             "url_fuente": "https://bo.gba.gob.ar/x", "propuesta": {}, "creado_en": "2026-11-04T10:00"},
            {"id": "2", "agente": "rastreador", "tipo": "documento_nuevo", "titulo": "COPAR", "estado": "pendiente",
             "url_fuente": "https://copar/n/", "propuesta": {}, "creado_en": "2026-11-04T10:00"},
            {"id": "3", "agente": "rastreador", "tipo": "documento_nuevo", "titulo": "COPAR", "estado": "pendiente",
             "url_fuente": "https://copar/n/", "propuesta": {}, "creado_en": "2026-11-03T10:00"},
            {"id": "4", "agente": "control_vigencia", "tipo": "propuesta_cambio", "titulo": "v", "estado": "pendiente",
             "propuesta": {"accion": "marcar_no_vigente", "parametros": {"autoridad_id": "a1"}}, "creado_en": "2026-11-04"},
            {"id": "5", "agente": "control_vigencia", "tipo": "propuesta_cambio", "titulo": "v", "estado": "pendiente",
             "propuesta": {"accion": "marcar_no_vigente", "parametros": {"autoridad_id": "a1"}}, "creado_en": "2026-11-02"},
            {"id": "6", "agente": "control_vigencia", "tipo": "propuesta_cambio", "titulo": "v", "estado": "pendiente",
             "propuesta": {"accion": "marcar_no_vigente", "parametros": {"autoridad_id": "viejo"}}, "creado_en": "2026-11-02"},
            {"id": "7", "agente": "relevador_faba", "tipo": "propuesta_cambio", "titulo": "otro", "estado": "pendiente",
             "propuesta": {}, "creado_en": "2026-11-02"}]
        fdb = FakeDB({"cola_revision": cola, "fuentes_monitoreadas": [{"url": "https://bo.gba.gob.ar/x", "tipo": "boletin_oficial"},
                                                                         {"url": "https://copar/n/", "tipo": "sitio_oficial"}],
                      "autoridades": [{"id": "a1", "vigente": True}, {"id": "viejo", "vigente": False}]})
        with mock.patch.object(o, "db", return_value=fdb), mock.patch.object(l.o, "db", return_value=fdb), mock.patch("sys.argv", ["x"]):
            l.main()
        estado = {c["id"]: c["estado"] for c in fdb.tablas["cola_revision"]}
        self.assertEqual(estado, {"1": "rechazada", "2": "pendiente", "3": "rechazada", "4": "pendiente",
                                  "5": "rechazada", "6": "rechazada", "7": "pendiente"})


if __name__ == "__main__":
    unittest.main()
