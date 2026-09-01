"""Backfill seguro de documentos históricos al tenant ``cibercom``.

Sin ``--apply`` el comando es estrictamente de lectura. Nunca elimina ni
reemplaza documentos y nunca modifica un ``org_id`` existente.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from pymongo import MongoClient


DEFAULT_COLLECTIONS = (
    "usuario", "empleados", "rh", "catalogodepto", "comportamientolaboral",
    "datoscontacto", "direccion", "educacion", "expedienteclinico",
    "personascontacto", "prestamo", "redsocial", "jerarquia", "roles_custom",
    "documentosfinancieros", "vacaciones", "notificaciones", "auditoria",
    "nomina_parametros", "candidatos", "evaluaciones", "conexiones_externas",
)


def _collection_report(collection, target_org_id):
    total = collection.count_documents({})
    without_org = collection.count_documents({"org_id": {"$exists": False}})
    target_org = collection.count_documents({"org_id": target_org_id})
    other_org = total - without_org - target_org
    return {
        "total": total,
        "without_org": without_org,
        "target_org": target_org,
        "other_org": other_org,
    }


def build_report(db, collections, target_org_id="cibercom"):
    return {
        name: _collection_report(getattr(db, name), target_org_id)
        for name in collections
    }


def _bootstrap_cibercom(db, target_org_id):
    now = datetime.now(timezone.utc).isoformat()
    db.tenants.update_one(
        {"org_id": target_org_id},
        {"$setOnInsert": {
            "org_id": target_org_id,
            "nombre": "Cibercom",
            "estado": "activo",
            "fecha_alta": now,
        }},
        upsert=True,
    )
    db.organizacion.update_one(
        {"org_id": target_org_id},
        {"$setOnInsert": {"org_id": target_org_id, "name": "CibercomHR"}},
        upsert=True,
    )


def backfill(db, collections=DEFAULT_COLLECTIONS, target_org_id="cibercom", apply=False):
    before = build_report(db, collections, target_org_id)
    updated = {name: 0 for name in collections}

    if apply:
        for name in collections:
            result = getattr(db, name).update_many(
                {"org_id": {"$exists": False}},
                {"$set": {"org_id": target_org_id}},
            )
            updated[name] = result.modified_count
        _bootstrap_cibercom(db, target_org_id)

    after = build_report(db, collections, target_org_id)
    report = {}
    for name in collections:
        if before[name]["total"] != after[name]["total"]:
            raise RuntimeError(f"El total de documentos cambió en {name}")
        report[name] = {
            "before": before[name],
            "after": after[name],
            "updated": updated[name],
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Aplicar el backfill")
    parser.add_argument("--org-id", default="cibercom")
    args = parser.parse_args()

    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        raise SystemExit("Falta MONGO_URI; no se realizó ninguna operación")
    db_name = os.environ.get("MONGO_DB_NAME", "controlempleados")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=8000)
    db = client[db_name]
    report = backfill(db, DEFAULT_COLLECTIONS, args.org_id, apply=args.apply)
    print(json.dumps({"applied": args.apply, "collections": report}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
