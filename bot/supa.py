"""Cliente mínimo de la API REST de Supabase (PostgREST), sin dependencias externas.
Funciona con las claves nuevas (sb_secret_… / sb_publishable_…) y con las legacy (JWT).
Implementa solo lo que usan los agentes: table().select/eq/in_/gte/lte/lt/is_/order/limit/
insert/update/upsert().execute() y rpc().execute()."""
import json
import urllib.error
import urllib.parse
import urllib.request


class SupaError(Exception):
    def __init__(self, status, mensaje, codigo=None):
        super().__init__(f"HTTP {status}: {mensaje}")
        self.status, self.mensaje, self.codigo = status, mensaje, codigo


class Resp:
    def __init__(self, data, status):
        self.data, self.status = data, status


def _valor(v):
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)


class Query:
    def __init__(self, cli, tabla):
        self.cli, self.tabla = cli, tabla
        self.metodo, self.cuerpo, self.params, self.prefer = "GET", None, [], []

    # --- lectura
    def select(self, cols="*"):
        self.params.append(("select", cols)); return self

    def eq(self, c, v):  self.params.append((c, "eq." + _valor(v))); return self
    def neq(self, c, v): self.params.append((c, "neq." + _valor(v))); return self
    def gte(self, c, v): self.params.append((c, "gte." + _valor(v))); return self
    def lte(self, c, v): self.params.append((c, "lte." + _valor(v))); return self
    def lt(self, c, v):  self.params.append((c, "lt." + _valor(v))); return self

    def in_(self, c, valores):
        lista = ",".join('"' + str(v).replace('"', '\\"') + '"' for v in valores)
        self.params.append((c, f"in.({lista})")); return self

    def is_(self, c, v):
        self.params.append((c, "is." + ("null" if v is None else _valor(v)))); return self

    def order(self, c, desc=False):
        self.params.append(("order", f"{c}.{'desc' if desc else 'asc'}")); return self

    def limit(self, n):
        self.params.append(("limit", str(int(n)))); return self

    # --- escritura
    def insert(self, filas):
        self.metodo, self.cuerpo = "POST", filas
        self.prefer.append("return=representation"); return self

    def update(self, valores):
        self.metodo, self.cuerpo = "PATCH", valores
        self.prefer.append("return=representation"); return self

    def upsert(self, filas, on_conflict=None):
        self.metodo, self.cuerpo = "POST", filas
        self.prefer += ["return=representation", "resolution=merge-duplicates"]
        if on_conflict:
            self.params.append(("on_conflict", on_conflict))
        return self

    def delete(self):
        self.metodo, self.cuerpo = "DELETE", None
        self.prefer.append("return=representation"); return self

    def url(self):
        q = urllib.parse.urlencode(self.params, safe="(),.*\"")
        return f"{self.cli.url}/rest/v1/{self.tabla}" + (f"?{q}" if q else "")

    def execute(self):
        if self.metodo in ("PATCH", "DELETE") and not any(k not in ("select", "order", "limit") for k, _ in self.params):
            raise SupaError(0, "update/delete sin filtro: se rechaza para no modificar toda la tabla")
        return self.cli._pedir(self.metodo, self.url(), self.cuerpo, self.prefer)


class Rpc:
    def __init__(self, cli, fn, params):
        self.cli, self.fn, self.p = cli, fn, params or {}

    def execute(self):
        return self.cli._pedir("POST", f"{self.cli.url}/rest/v1/rpc/{self.fn}", self.p, [])


class Cliente:
    def __init__(self, url, clave, timeout=30):
        if not url or not clave:
            raise ValueError("Faltan la URL o la clave de Supabase.")
        self.url, self.clave, self.timeout = url.rstrip("/"), clave, timeout

    def cabeceras(self):
        h = {"apikey": self.clave, "Content-Type": "application/json", "Accept": "application/json"}
        if self.clave.count(".") == 2 and self.clave.startswith("eyJ"):    # clave legacy (JWT)
            h["Authorization"] = f"Bearer {self.clave}"
        return h

    def table(self, nombre):
        return Query(self, nombre)

    def rpc(self, fn, params=None):
        return Rpc(self, fn, params)

    def _pedir(self, metodo, url, cuerpo, prefer):
        h = self.cabeceras()
        if prefer:
            h["Prefer"] = ",".join(prefer)
        datos = None if cuerpo is None else json.dumps(cuerpo, ensure_ascii=False, default=str).encode()
        req = urllib.request.Request(url, data=datos, method=metodo, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                txt = r.read().decode() or "null"
                return Resp(json.loads(txt), r.getcode())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode() or "{}")
            except Exception:
                err = {}
            raise SupaError(e.code, err.get("message") or e.reason, err.get("code")) from None
