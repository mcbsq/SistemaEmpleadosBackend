# Índices parciales de la integración. Por defecto solo imprime.
# No abre Mongo y no toca la base real. No borra duplicados: si los hay,
# informa el conflicto y no crea ese índice.
#
# Para una base desechable, y solo esa:
#   APLICAR_INDICES_DESECHABLE=1 MONGO_URI=mongodb://127.0.0.1:27028/desechable python scripts/migracion_indices_aegis.py
import os
import sys

def _presente(campo):
    return {"$and": [{campo: {"$type": "string"}}, {campo: {"$gt": ""}}]}


def _y(*partes):
    filtro = []
    for parte in partes:
        filtro.extend(parte["$and"])
    return {"$and": filtro}


# Únicos solo cuando el vínculo o la clave ya están completos.
# Cuentas legacy sin UUID y solicitudes sin Idempotency-Key quedan fuera.
INDICES = (
    {
        "coleccion": "designacion_admin",
        "claves": [("org_id", 1)],
        "unique": True,
        "parcial": _presente("org_id"),
        "auditoria": ("org_id",),
    },
    {
        "coleccion": "usuario",
        "claves": [("aegis_user_id", 1), ("aegis_tenant_id", 1)],
        "unique": True,
        "parcial": _y(_presente("aegis_user_id"), _presente("aegis_tenant_id")),
        "auditoria": ("aegis_user_id", "aegis_tenant_id"),
    },
    {
        "coleccion": "tenant_correspondencia",
        "claves": [("org_id", 1), ("app_key", 1)],
        "unique": True,
        "parcial": _y(_presente("org_id"), _presente("app_key")),
        "auditoria": ("org_id", "app_key"),
    },
    {
        "coleccion": "tenant_correspondencia",
        "claves": [("aegis_tenant_id", 1), ("app_key", 1)],
        "unique": True,
        "parcial": _y(_presente("aegis_tenant_id"), _presente("app_key")),
        "auditoria": ("aegis_tenant_id", "app_key"),
    },
    {
        "coleccion": "sesiones",
        "claves": [("sid", 1)],
        "unique": True,
        "parcial": _presente("sid"),
        "auditoria": ("sid",),
    },
    {
        "coleccion": "solicitudes_acceso",
        "claves": [("idempotencia", 1)],
        "unique": True,
        "parcial": _presente("idempotencia"),
        "auditoria": ("idempotencia",),
    },
    {
        "coleccion": "solicitudes_acceso",
        "claves": [("correo", 1), ("empresa_norm", 1), ("estado", 1)],
        "unique": False,
        "parcial": None,
        "auditoria": (),
    },
)


def duplicados(db, coleccion, campos, parcial):
    grupo_id = {campo: f"${campo}" for campo in campos}
    filas = db[coleccion].aggregate([
        {"$match": parcial},
        {"$group": {"_id": grupo_id, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ])
    return list(filas)


def aplicar_indices(db):
    """
    Crea los índices que no tengan duplicados. Devuelve la lista de
    conflictos y no borra documentos.
    """
    conflictos = []
    for spec in INDICES:
        if spec["unique"] and spec["auditoria"]:
            hallados = duplicados(db, spec["coleccion"], spec["auditoria"], spec["parcial"])
            if hallados:
                conflictos.append({
                    "coleccion": spec["coleccion"],
                    "claves": spec["auditoria"],
                    "grupos": hallados,
                })
                continue
        kwargs = {"unique": spec["unique"]}
        if spec["parcial"]:
            kwargs["partialFilterExpression"] = spec["parcial"]
        db[spec["coleccion"]].create_index(spec["claves"], **kwargs)
    return conflictos


def main():
    print("Índices previstos para la integración. aplicado=false")
    for spec in INDICES:
        print(
            f"  {spec['coleccion']} {spec['claves']} unique={spec['unique']} "
            f"parcial={spec['parcial']}"
        )
    if os.environ.get("APLICAR_INDICES_DESECHABLE") != "1":
        print("No se conectó a ninguna base.")
        return 0
    uri = (os.environ.get("MONGO_URI") or "").strip()
    if not uri or "mongodb.net" in uri or "desechable" not in uri.lower():
        print("MONGO_URI tiene que ser una base local cuyo nombre contenga 'desechable'.")
        return 2
    from pymongo import MongoClient
    cliente = MongoClient(uri, serverSelectionTimeoutMS=2000)
    db = cliente.get_default_database()
    conflictos = aplicar_indices(db)
    if conflictos:
        print("Hay duplicados. No se borró nada y esos índices no se crearon.")
        for conflicto in conflictos:
            print(f"  {conflicto['coleccion']} {conflicto['claves']} grupos={len(conflicto['grupos'])}")
        return 3
    print("Índices creados en la base desechable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
