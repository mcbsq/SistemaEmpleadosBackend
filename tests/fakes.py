# tests/fakes.py
# ─────────────────────────────────────────────────────────────────────────────
# Mongo falso en memoria — suficiente para probar la lógica de negocio
# (generación/validación/consumo de API keys) sin depender de una base de
# datos real. Solo implementa lo que estos módulos realmente usan.
import itertools
from bson.objectid import ObjectId


def _matches(doc, filtro):
    for k, v in (filtro or {}).items():
        actual = doc.get(k)
        if isinstance(v, dict) and any(str(op).startswith("$") for op in v):
            for op, opval in v.items():
                if op == "$ne":
                    if actual == opval:
                        return False
                elif op == "$in":
                    if actual not in opval:
                        return False
                elif op == "$nin":
                    if actual in opval:
                        return False
                else:
                    raise NotImplementedError(f"FakeCollection no soporta el operador {op}")
        elif actual != v:
            return False
    return True


class FakeCursor(list):
    """list con .sort(campo, direccion) encadenable, para imitar lo poco que
    estos módulos usan de un cursor real de pymongo."""
    def sort(self, campo, direccion=-1):
        ordenado = sorted(self, key=lambda d: d.get(campo), reverse=(direccion == -1))
        self[:] = ordenado
        return self


class FakeCollection:
    def __init__(self):
        self._docs = {}
        self._counter = itertools.count(1)

    def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        self._docs[doc["_id"]] = doc
        return type("Result", (), {"inserted_id": doc["_id"]})()

    def find_one(self, filtro=None):
        for doc in self._docs.values():
            if _matches(doc, filtro):
                return dict(doc)
        return None

    def find(self, filtro=None):
        return FakeCursor(dict(d) for d in self._docs.values() if _matches(d, filtro))

    def update_one(self, filtro, update):
        for doc in self._docs.values():
            if _matches(doc, filtro):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                return type("Result", (), {"matched_count": 1, "modified_count": 1})()
        return type("Result", (), {"matched_count": 0, "modified_count": 0})()

    def delete_one(self, filtro):
        for _id, doc in list(self._docs.items()):
            if _matches(doc, filtro):
                del self._docs[_id]
                return type("Result", (), {"deleted_count": 1})()
        return type("Result", (), {"deleted_count": 0})()

    def count_documents(self, filtro=None):
        return len([d for d in self._docs.values() if _matches(d, filtro)])


class FakeDB:
    """Imita mongo.db.<coleccion> — suficiente atributo por nombre, sin
    aislamiento multi-tenant (las pruebas no corren dentro de una request
    Flask real, así que core/tenant_db.py no aplica aquí de todas formas)."""
    def __init__(self):
        self._colecciones = {}

    def __getattr__(self, nombre):
        if nombre not in self._colecciones:
            self._colecciones[nombre] = FakeCollection()
        return self._colecciones[nombre]


class FakeMongo:
    def __init__(self):
        self.db = FakeDB()
