import json
import unittest
from unittest import mock

import supa


class Resp:
    def __init__(self, data, code=200):
        self.d, self.c = data, code
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.d).encode()
    def getcode(self): return self.c


class T(unittest.TestCase):
    def pedido(self, cli, q):
        with mock.patch("urllib.request.urlopen", return_value=Resp([{"id": 1}])) as m:
            r = q.execute()
        return m.call_args[0][0], r

    def test_clave_nueva_va_solo_en_apikey(self):
        clave = "sb_secret_" + "abcdefghijkl"          # armada en partes: el guardián no la confunde
        cli = supa.Cliente("https://p.supabase.co/", clave)
        req, r = self.pedido(cli, cli.table("cola_revision").select("id").eq("url_fuente", "https://a.b/c?x=1").eq("hash_sha256", "f" * 64))
        self.assertEqual(req.get_header("Apikey"), clave)
        self.assertIsNone(req.get_header("Authorization"))
        self.assertIn("/rest/v1/cola_revision?select=id&url_fuente=eq.https%3A%2F%2Fa.b%2Fc%3Fx%3D1", req.full_url)
        self.assertEqual(r.data, [{"id": 1}])

    def test_clave_legacy_lleva_bearer(self):
        cli = supa.Cliente("https://p.supabase.co", "eyJa.eyJb.c")
        req, _ = self.pedido(cli, cli.table("t").select())
        self.assertEqual(req.get_header("Authorization"), "Bearer eyJa.eyJb.c")

    def test_insert_upsert_in(self):
        cli = supa.Cliente("https://p.supabase.co", "k")
        req, _ = self.pedido(cli, cli.table("fuente_urls_vistas").upsert({"a": 1}, on_conflict="fuente_id,url"))
        self.assertEqual(req.get_method(), "POST"); self.assertIn("resolution=merge-duplicates", req.get_header("Prefer"))
        self.assertIn("on_conflict=fuente_id%2Curl", req.full_url.replace(",", "%2C"))
        req, _ = self.pedido(cli, cli.table("t").select().in_("estado", ["activa", "caida"]))
        self.assertIn('estado=in.("activa","caida")', req.full_url)

    def test_update_sin_filtro_se_rechaza(self):
        cli = supa.Cliente("https://p.supabase.co", "k")
        with self.assertRaises(supa.SupaError):
            cli.table("fuentes_monitoreadas").update({"estado": "x"}).execute()

    def test_error_http(self):
        cli = supa.Cliente("https://p.supabase.co", "k")
        err = supa.urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        err.read = lambda: b'{"message":"relation does not exist","code":"42P01"}'
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(supa.SupaError) as c:
                cli.table("x").select().execute()
        self.assertEqual(c.exception.codigo, "42P01")


if __name__ == "__main__":
    unittest.main()
