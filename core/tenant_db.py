# core/tenant_db.py
# ─────────────────────────────────────────────────────────────────────────────
# Aislamiento multi-tenant real: cada empresa (org_id) tiene sus propios
# empleados, RH, vacaciones, etc. — completamente invisibles para las demás,
# igual que workspaces separados de Notion.
#
# Antes de esto, `org_id` viajaba en el JWT pero NINGÚN endpoint de datos
# (empleados, rh, vacaciones, documentosfinancieros, candidatos...) lo usaba
# para filtrar — dos empresas en el mismo despliegue verían la misma
# información. Tocar a mano cada uno de los ~30 módulos para agregar
# `{"org_id": org_id}` en cada find/insert/update es exactamente el tipo de
# cambio donde un solo endpoint olvidado es una fuga de datos entre clientes.
#
# En vez de eso, este módulo envuelve `mongo.db` una sola vez (en app.py) con
# un proxy: cada colección "sensible" queda automáticamente filtrada/etiquetada
# con `org_id` tomado de `flask.g.org_id` (fijado en el before_request al
# validar el JWT — ver app.py). Ningún módulo de api/* necesitó cambiar una
# sola línea para quedar aislado.
#
# org_id = el tenant_key resuelto por Aegis en el login (ver api/login/logic.py).
# Para bypass explícito y deliberado (validación de API keys entrantes, que
# deben buscar por hash SIN saber a qué tenant pertenecen todavía, y el
# script de migración), usar `mongo.db.raw.<coleccion>` — accede a pymongo
# directo, sin ningún filtro automático. Usar con mucho cuidado.
from __future__ import annotations
import flask


class ContextoEmpresaFaltante(RuntimeError):
    """Una ruta privada consultó datos sin empresa resuelta."""


def _org_id_actual():
    """org_id de la request en curso, o None si no hay uno resuelto todavía
    (rutas públicas, bootstrap de login, o código corriendo fuera de una
    request — ej. el arranque de la app)."""
    try:
        return getattr(flask.g, "org_id", None)
    except RuntimeError:
        return None


class _ColeccionMultiTenant:
    """Envuelve una pymongo.collection.Collection: agrega org_id a los
    filtros de lectura/borrado/actualización y a los documentos nuevos."""

    def __init__(self, coleccion):
        self._col = coleccion

    def _exigir_contexto(self):
        try:
            privado = getattr(flask.g, "contexto_privado", False)
        except RuntimeError:
            return
        if privado and _org_id_actual() is None:
            raise ContextoEmpresaFaltante("falta el contexto de empresa")

    def _filtro(self, filtro):
        self._exigir_contexto()
        org_id = _org_id_actual()
        filtro = dict(filtro) if filtro else {}
        if org_id is not None:
            filtro["org_id"] = org_id
        return filtro

    def _sin_mudar_empresa(self, update):
        org_id = _org_id_actual()
        if org_id is None or not isinstance(update, dict):
            return update
        update = dict(update)
        for clave in ("$set", "$setOnInsert"):
            bloque = update.get(clave)
            if isinstance(bloque, dict) and bloque.get("org_id") not in (None, org_id):
                bloque = dict(bloque)
                bloque.pop("org_id", None)
                update[clave] = bloque
        return update

    def _doc_con_org(self, documento):
        self._exigir_contexto()
        documento = dict(documento) if documento else {}
        org_id = _org_id_actual()
        if org_id is not None:
            documento["org_id"] = org_id
        return documento

    def _update_con_org_en_upsert(self, update, kwargs):
        if kwargs.get("upsert") and isinstance(update, dict) and any(str(k).startswith("$") for k in update):
            org_id = _org_id_actual()
            if org_id is not None:
                update = dict(update)
                set_on_insert = dict(update.get("$setOnInsert", {}))
                set_on_insert["org_id"] = org_id
                update["$setOnInsert"] = set_on_insert
        return update

    # ── Lectura ──────────────────────────────────────────────────────────
    def find(self, filtro=None, *args, **kwargs):
        return self._col.find(self._filtro(filtro), *args, **kwargs)

    def find_one(self, filtro=None, *args, **kwargs):
        return self._col.find_one(self._filtro(filtro), *args, **kwargs)

    def count_documents(self, filtro=None, *args, **kwargs):
        return self._col.count_documents(self._filtro(filtro), *args, **kwargs)

    def distinct(self, key, filtro=None, *args, **kwargs):
        return self._col.distinct(key, self._filtro(filtro), *args, **kwargs)

    def aggregate(self, pipeline=None, *args, **kwargs):
        self._exigir_contexto()
        org_id = _org_id_actual()
        pipeline = list(pipeline or [])
        if org_id is not None:
            pipeline = [{"$match": {"org_id": org_id}}] + [
                self._lookup_aislado(etapa, org_id) for etapa in pipeline
            ]
        return self._col.aggregate(pipeline, *args, **kwargs)

    def _lookup_aislado(self, etapa, org_id):
        if not isinstance(etapa, dict) or "$lookup" not in etapa:
            return etapa
        lookup = dict(etapa["$lookup"])
        if "pipeline" in lookup:
            lookup["pipeline"] = [{"$match": {"org_id": org_id}}] + list(lookup["pipeline"])
            return {"$lookup": lookup}
        local = lookup.pop("localField", None)
        foraneo = lookup.pop("foreignField", "_id")
        lookup["let"] = {"fk": f"${local}" if local else None}
        lookup["pipeline"] = [
            {"$match": {"org_id": org_id}},
            {"$match": {"$expr": {"$eq": [f"${foraneo}", "$$fk"]}}},
        ]
        return {"$lookup": lookup}

    # ── Escritura ────────────────────────────────────────────────────────
    def insert_one(self, documento, *args, **kwargs):
        return self._col.insert_one(self._doc_con_org(documento), *args, **kwargs)

    def insert_many(self, documentos, *args, **kwargs):
        return self._col.insert_many([self._doc_con_org(d) for d in (documentos or [])], *args, **kwargs)

    def update_one(self, filtro, update, *args, **kwargs):
        update = self._sin_mudar_empresa(update)
        return self._col.update_one(self._filtro(filtro), self._update_con_org_en_upsert(update, kwargs), *args, **kwargs)

    def update_many(self, filtro, update, *args, **kwargs):
        update = self._sin_mudar_empresa(update)
        return self._col.update_many(self._filtro(filtro), self._update_con_org_en_upsert(update, kwargs), *args, **kwargs)

    def find_one_and_update(self, filtro, update, *args, **kwargs):
        update = self._sin_mudar_empresa(update)
        return self._col.find_one_and_update(self._filtro(filtro), self._update_con_org_en_upsert(update, kwargs), *args, **kwargs)

    def bulk_write(self, *args, **kwargs):
        raise ContextoEmpresaFaltante("bulk_write no está aislado por empresa")

    def replace_one(self, filtro, reemplazo, *args, **kwargs):
        return self._col.replace_one(self._filtro(filtro), self._doc_con_org(reemplazo), *args, **kwargs)

    def delete_one(self, filtro, *args, **kwargs):
        return self._col.delete_one(self._filtro(filtro), *args, **kwargs)

    def delete_many(self, filtro, *args, **kwargs):
        return self._col.delete_many(self._filtro(filtro), *args, **kwargs)

    # create_index y el resto pasan directo. Las lecturas y escrituras de
    # documentos van por los métodos de arriba. bulk_write está bloqueado.
    def __getattr__(self, nombre):
        if nombre in ("bulk_write", "find_raw_batches"):
            raise ContextoEmpresaFaltante(f"{nombre} no está aislado por empresa")
        return getattr(self._col, nombre)


class BaseDatosMultiTenant:
    """Sustituto de pymongo.database.Database — `mongo.db.empleados` sigue
    funcionando exactamente igual en cada módulo existente, pero ahora cada
    colección aísla por org_id automáticamente."""

    def __init__(self, db):
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_cache", {})

    def __getattr__(self, nombre):
        if nombre not in self._cache:
            self._cache[nombre] = _ColeccionMultiTenant(getattr(self._db, nombre))
        return self._cache[nombre]

    def get_collection(self, nombre, *args, **kwargs):
        return getattr(self, nombre)

    # mongo.db["coleccion"] — mismo aislamiento que mongo.db.coleccion. Sin
    # esto, el borrado en cascada de empleados (empleados/logic.py) tronaba
    # después de borrar al empleado y dejaba sus datos hijos huérfanos.
    def __getitem__(self, nombre):
        return getattr(self, nombre)

    def command(self, *args, **kwargs):
        return self._db.command(*args, **kwargs)

    @property
    def raw(self):
        """Escape hatch deliberado: acceso directo a pymongo, SIN filtrar por
        org_id. Solo para: (1) validar API keys entrantes por hash antes de
        saber a qué tenant pertenecen, (2) el script de migración/backfill,
        (3) operaciones de plataforma que deliberadamente cruzan tenants
        (ej. el listado de empresas para el operador). Cualquier otro uso es
        casi seguro un bug de aislamiento — pensarlo dos veces."""
        return self._db
