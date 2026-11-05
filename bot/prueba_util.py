"""Base de datos falsa en memoria para los tests (misma interfaz que supa.Cliente). No es un test."""
import copy
import uuid

from supa import Resp, SupaError


class _Q:
    def __init__(self, fdb, tabla):
        self.fdb, self.tabla, self.filtros, self.op, self.valor = fdb, tabla, [], "select", None
        self.conflict, self._limit, self._order = None, None, None

    def select(self, cols="*"):
        return self

    def _f(self, fn):
        self.filtros.append(fn); return self

    def eq(self, c, v):  return self._f(lambda r: r.get(c) == v)
    def neq(self, c, v): return self._f(lambda r: r.get(c) != v)
    def gte(self, c, v): return self._f(lambda r: r.get(c) is not None and str(r.get(c)) >= str(v))
    def lte(self, c, v): return self._f(lambda r: r.get(c) is not None and str(r.get(c)) <= str(v))
    def lt(self, c, v):  return self._f(lambda r: r.get(c) is not None and str(r.get(c)) < str(v))
    def in_(self, c, vs): return self._f(lambda r: r.get(c) in list(vs))
    def is_(self, c, v): return self._f(lambda r: r.get(c) is v)

    def order(self, c, desc=False):
        self._order = (c, desc); return self

    def limit(self, n):
        self._limit = n; return self

    def insert(self, filas):
        self.op, self.valor = "insert", filas; return self

    def update(self, v):
        self.op, self.valor = "update", v; return self

    def delete(self):
        self.op, self.valor = "delete", None; return self

    def upsert(self, filas, on_conflict=None):
        self.op, self.valor, self.conflict = "upsert", filas, on_conflict; return self

    def execute(self):
        if self.tabla in self.fdb.faltantes:
            raise SupaError(404, f"relation {self.tabla} does not exist", "PGRST205")
        filas = self.fdb.tablas.setdefault(self.tabla, [])
        self.fdb.log.append((self.op, self.tabla))
        if self.op == "select":
            out = [copy.deepcopy(r) for r in filas if all(f(r) for f in self.filtros)]
            if self._order:
                out.sort(key=lambda r: str(r.get(self._order[0]) or ""), reverse=self._order[1])
            return Resp(out[: self._limit] if self._limit else out, 200)
        lista = self.valor if isinstance(self.valor, list) else [self.valor]
        if self.op == "insert":
            nuevas = []
            for v in lista:
                r = {"id": str(uuid.uuid4()), **copy.deepcopy(v)}
                filas.append(r); nuevas.append(copy.deepcopy(r))
            return Resp(nuevas, 201)
        if self.op == "update":
            if not self.filtros:
                raise SupaError(0, "update sin filtro")
            cambiadas = []
            for r in filas:
                if all(f(r) for f in self.filtros):
                    r.update(copy.deepcopy(self.valor)); cambiadas.append(copy.deepcopy(r))
            return Resp(cambiadas, 200)
        if self.op == "delete":
            if not self.filtros:
                raise SupaError(0, "delete sin filtro")
            borradas = [r for r in filas if all(fn(r) for fn in self.filtros)]
            self.fdb.tablas[self.tabla] = [r for r in filas if r not in borradas]
            return Resp(copy.deepcopy(borradas), 200)
        if self.op == "upsert":
            claves = (self.conflict or "id").split(",")
            out = []
            for v in lista:
                previa = next((r for r in filas if all(r.get(k) == v.get(k) for k in claves)), None)
                if previa:
                    previa.update(copy.deepcopy(v)); out.append(copy.deepcopy(previa))
                else:
                    r = {"id": str(uuid.uuid4()), **copy.deepcopy(v)}; filas.append(r); out.append(copy.deepcopy(r))
            return Resp(out, 201)
        raise AssertionError(self.op)


class FakeDB:
    def __init__(self, tablas=None, faltantes=()):
        self.tablas = copy.deepcopy(tablas or {})
        self.faltantes = set(faltantes)
        self.log = []

    def table(self, nombre):
        return _Q(self, nombre)

    def escrituras(self):
        return {t for op, t in self.log if op != "select"}
