# Almacén desechable con transacción inmediata. Sirve para probar el lease
# entre dos procesos sin abrir la Mongo del proyecto.
import json
import sqlite3

from tests.fakes import _matches


class ColeccionSqlite:
    def __init__(self, path, nombre):
        self.path = path
        self.nombre = nombre
        con = sqlite3.connect(path)
        con.execute(
            "create table if not exists docs (id integer primary key autoincrement, col text, body text)"
        )
        con.commit()
        con.close()

    def _begin(self):
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.execute("BEGIN IMMEDIATE")
        return con

    def insert_one(self, doc):
        con = self._begin()
        try:
            con.execute(
                "insert into docs(col, body) values (?, ?)",
                (self.nombre, json.dumps(doc)),
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return type("Result", (), {"inserted_id": None})()

    def find_one(self, filtro=None):
        con = sqlite3.connect(self.path, timeout=30)
        try:
            rows = con.execute("select body from docs where col=?", (self.nombre,)).fetchall()
        finally:
            con.close()
        for (body,) in rows:
            doc = json.loads(body)
            if _matches(doc, filtro):
                return doc
        return None

    def find_one_and_update(self, filtro, update, upsert=False):
        con = self._begin()
        try:
            rows = list(con.execute("select id, body from docs where col=?", (self.nombre,)))
            for id_, body in rows:
                doc = json.loads(body)
                if not _matches(doc, filtro):
                    continue
                antes = dict(doc)
                doc.update(update.get("$set") or {})
                con.execute("update docs set body=? where id=?", (json.dumps(doc), id_))
                con.execute("COMMIT")
                return antes
            con.execute("COMMIT")
            return None
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def update_one(self, filtro, update, upsert=False):
        con = self._begin()
        try:
            rows = list(con.execute("select id, body from docs where col=?", (self.nombre,)))
            for id_, body in rows:
                doc = json.loads(body)
                if not _matches(doc, filtro):
                    continue
                doc.update(update.get("$set") or {})
                con.execute("update docs set body=? where id=?", (json.dumps(doc), id_))
                con.execute("COMMIT")
                return type("Result", (), {"matched_count": 1, "modified_count": 1})()
            con.execute("COMMIT")
            return type("Result", (), {"matched_count": 0, "modified_count": 0})()
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()


class _Raw:
    def __init__(self, path):
        self.path = path
        self._cols = {}

    def __getattr__(self, nombre):
        if nombre not in self._cols:
            self._cols[nombre] = ColeccionSqlite(self.path, nombre)
        return self._cols[nombre]


class Envoltura:
    def __init__(self, path):
        self.db = self
        self.raw = _Raw(path)
