# scripts/migrar_multi_tenant.py
# ─────────────────────────────────────────────────────────────────────────────
# Migración única: backfill de `org_id` en cada documento existente que no lo
# tenga todavía. Todo lo que ya vive en esta base pertenece a Cibercom (el
# único tenant que ha usado el sistema hasta ahora), así que se etiqueta como
# org_id="cibercom" — el mismo tenant_key que ya resuelve Aegis para nuestras
# cuentas reales (ver memoria aegis-integration-state).
#
# Idempotente: solo toca documentos SIN el campo org_id, así que correrlo dos
# veces no hace nada la segunda vez. Ejecutar una sola vez, después de
# desplegar el aislamiento multi-tenant (core/tenant_db.py) y antes de dar de
# alta cualquier empresa nueva.
#
# Uso: venv/bin/python scripts/migrar_multi_tenant.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(".env.local")
except ImportError:
    pass

from pymongo import MongoClient

ORG_ID_CIBERCOM = "cibercom"

# Todas las colecciones que este backend usa y que deben quedar aisladas por
# empresa (ver core/tenant_db.py para el porqué de la lista completa).
COLECCIONES_A_MIGRAR = [
    "empleados", "rh", "expedienteclinico", "educacion", "datoscontacto",
    "personascontacto", "direccion", "redsocial", "usuario",
    "vacaciones_solicitudes", "documentosfinancieros", "evaluaciones",
    "ciclos_evaluacion", "vacantes", "candidatos", "notificaciones",
    "audit_log", "roles_custom", "analitica_permisos", "api_keys",
    "jerarquia_empleados", "sistema_flags", "organizacion",
    "nomina_parametros", "catalogodepto", "comportamientolaboral",
    "prestamo", "incidents",
]


def main():
    uri = os.environ["MONGO_URI"]
    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    db = client["controlempleados"]

    print(f"Migrando a org_id='{ORG_ID_CIBERCOM}' — base 'controlempleados'\n")
    total = 0
    for nombre in COLECCIONES_A_MIGRAR:
        col = db[nombre]
        resultado = col.update_many(
            {"org_id": {"$exists": False}},
            {"$set": {"org_id": ORG_ID_CIBERCOM}},
        )
        if resultado.modified_count:
            print(f"  {nombre:28s} {resultado.modified_count} documentos etiquetados")
        total += resultado.modified_count

    print(f"\nListo — {total} documentos migrados en total.")
    if total == 0:
        print("(Nada que migrar: o ya se corrió antes, o la base está vacía.)")


if __name__ == "__main__":
    main()
