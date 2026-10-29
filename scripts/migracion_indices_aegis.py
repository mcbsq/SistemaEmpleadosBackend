# Índices que hacen atómicas la designación, el vínculo y la solicitud.
# Por defecto solo imprime. No abre Mongo y no toca la base real.
#
# Para una base desechable, y solo esa:
#   APLICAR_INDICES_DESECHABLE=1 MONGO_URI=mongodb://127.0.0.1:27017/desechable python scripts/migracion_indices_aegis.py
import os
import sys

INDICES = (
    ("designacion_admin", [("org_id", 1)], True),
    ("usuario", [("aegis_user_id", 1), ("aegis_tenant_id", 1)], True),
    ("tenant_correspondencia", [("org_id", 1), ("app_key", 1)], True),
    ("tenant_correspondencia", [("aegis_tenant_id", 1), ("app_key", 1)], True),
    ("sesiones", [("sid", 1)], True),
    ("solicitudes_acceso", [("idempotencia", 1)], True),
    ("solicitudes_acceso", [("correo", 1), ("empresa_norm", 1), ("estado", 1)], False),
)


def main():
    print("Índices previstos para la integración. aplicado=false")
    for coleccion, claves, unico in INDICES:
        print(f"  {coleccion} {claves} unique={unico}")
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
    for coleccion, claves, unico in INDICES:
        db[coleccion].create_index(claves, unique=unico)
    print("Índices creados en la base desechable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
