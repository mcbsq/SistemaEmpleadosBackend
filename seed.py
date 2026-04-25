"""
seed.py — Cuentas maestras de prueba
Cibercom Sistema de Empleados 2026

Uso:
    python seed.py

Crea 3 empleados y sus cuentas de usuario para probar los 3 roles.
Es seguro ejecutarlo varias veces — verifica antes de insertar.

Integración Aegis:
  Si están definidos AEGIS_BASE_URL, AEGIS_TENANT_ID, AEGIS_APP_ID y AEGIS_API_KEY,
  cada usuario se crea primero en Aegis (contraseña allí) y en Mongo solo se guardan
  email, aegis_user_id, role, empleado_id (sin campo password).

  Sin API key pero con login Aegis configurado, el script avisa y termina sin crear
  usuarios (igual que POST /usuario en la API).

  Correos de seed: campo opcional "email" por cuenta; si falta, se usa
  {user}@{SEED_EMAIL_DOMAIN} (default: redcibercom.com.mx).
"""

import os
import sys
from datetime import datetime

from pymongo import MongoClient
from werkzeug.security import generate_password_hash

# Permite `python seed.py` desde la raíz del proyecto (import core.*)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.aegis_config import get_aegis_settings
from core.aegis_client import aegis_admin_create_user

# ─── Conexión ────────────────────────────────────────────────────────────────
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://cibercom:proyectos2022@cluster0.ilngp.mongodb.net/controlempleados?retryWrites=true&w=majority",
)
client = MongoClient(MONGO_URI)
db = client["controlempleados"]

# Dominio sintético para emails de prueba si no defines "email" en cada cuenta
SEED_EMAIL_DOMAIN = os.environ.get("SEED_EMAIL_DOMAIN", "redcibercom.com.mx")

# ─── Cuentas a crear ─────────────────────────────────────────────────────────
# "email" opcional; si no viene, se arma {user}@{SEED_EMAIL_DOMAIN}
CUENTAS = [
    {
        "user":     "superadmin_test",
        "password": "Super@2026",
        "role":     "SUPER_ADMIN",
        "empleado": {
            "Nombre":       "Super",
            "ApelPaterno":  "Admin",
            "ApelMaterno":  "Test",
            "FecNacimiento": "1985-01-01",
            "Fotografias":  [],
            "depto_id":     "DIRECTION",
            "Cargo":        "Director General",
        },
    },
    {
        "user":     "admin_test",
        "password": "Admin@2026",
        "role":     "ADMIN",
        "empleado": {
            "Nombre":       "Admin",
            "ApelPaterno":  "Área",
            "ApelMaterno":  "Test",
            "FecNacimiento": "1990-05-15",
            "Fotografias":  [],
            "depto_id":     "TECH",
            "Cargo":        "Jefe de Tecnología",
        },
    },
    {
        "user":     "employee_test",
        "password": "Employee@2026",
        "role":     "EMPLOYEE",
        "empleado": {
            "Nombre":       "Empleado",
            "ApelPaterno":  "Regular",
            "ApelMaterno":  "Test",
            "FecNacimiento": "1995-08-20",
            "Fotografias":  [],
            "depto_id":     "TECH",
            "Cargo":        "Desarrollador",
        },
    },
]


def _seed_email(cuenta: dict) -> str:
    raw = (cuenta.get("email") or "").strip()
    if raw:
        return raw.lower()
    return f"{cuenta['user']}@{SEED_EMAIL_DOMAIN}".lower()


def _ya_existe_usuario(user: str, email: str) -> bool:
    """Evita duplicar por login corto o por email (modo Aegis)."""
    return db.usuario.find_one(
        {"$or": [{"user": user}, {"email": email}]}
    ) is not None


def seed():
    print("\n=== SEED: Cuentas de prueba Cibercom ===\n")

    s = get_aegis_settings()
    if s["login_enabled"] and not s["admin_enabled"]:
        print(
            "  ✗  Login Aegis está configurado pero falta AEGIS_API_KEY.\n"
            "     No se pueden crear usuarios coherentes con ese login. "
            "Define la API key o desactiva Aegis (quita URL/tenant/app o pon AEGIS_DISABLED=true).\n"
        )
        return

    if s["admin_enabled"]:
        print("  Modo: Aegis (usuarios + contraseña en IdP; Mongo con email + aegis_user_id)\n")
    else:
        print("  Modo: legacy (hash de contraseña solo en Mongo)\n")

    for cuenta in CUENTAS:
        user = cuenta["user"]
        role = cuenta["role"]
        email = _seed_email(cuenta)

        if _ya_existe_usuario(user, email):
            print(f"  ⚠  '{user}' o email '{email}' ya existe — omitiendo.")
            continue

        emp_data = {
            **cuenta["empleado"],
            "createdAt": datetime.utcnow(),
        }
        emp_result = db.empleados.insert_one(emp_data)
        empleado_id = str(emp_result.inserted_id)

        db.rh.insert_one({
            "empleado_id": empleado_id,
            "Puesto":      cuenta["empleado"]["Cargo"],
            "depto_id":    cuenta["empleado"]["depto_id"],
            "JefeInmediato": "",
            "HorarioLaboral": {
                "HoraEntrada":    "09:00",
                "HoraSalida":     "18:00",
                "TiempoComida":   "1 hora",
                "DiasTrabajados": "Lunes a Viernes",
            },
        })

        if s["admin_enabled"]:
            # Contraseña y cuenta de login viven en Aegis; aquí solo enlazamos.
            created, err = aegis_admin_create_user(email, cuenta["password"])
            if err:
                body, status = err
                print(f"  ✗  Aegis rechazó alta para '{user}' ({email}): {status} {body}")
                print(
                    f"     Empleado {empleado_id} quedó sin usuario. "
                    "Borra empleado/rh en Mongo o corrige Aegis y vuelve a ejecutar.\n"
                )
                continue

            aegis_id = created.get("id") or created.get("user_id")
            if not aegis_id:
                print(f"  ✗  Respuesta Aegis sin id para '{user}': {created}\n")
                continue

            db.usuario.insert_one({
                "user":          user,
                "role":          role,
                "empleado_id":   empleado_id,
                "email":         email,
                "aegis_user_id": aegis_id,
            })
        else:
            hashed = generate_password_hash(cuenta["password"])
            doc = {
                "user":        user,
                "password":    hashed,
                "role":        role,
                "empleado_id": empleado_id,
            }
            if email:
                doc["email"] = email
            db.usuario.insert_one(doc)

        print(f"  ✓  '{user}' creado")
        print(f"     Role:        {role}")
        print(f"     Password:    {cuenta['password']}")
        print(f"     Email seed:  {email}")
        print(f"     Empleado ID: {empleado_id}")
        print(f"     Depto:       {cuenta['empleado']['depto_id']}\n")

    print("=== Resumen de cuentas disponibles ===\n")
    print("  Usuario           Contraseña       Rol")
    print("  ──────────────────────────────────────────────")
    for c in CUENTAS:
        print(f"  {c['user']:<18} {c['password']:<16} {c['role']}")
    if s["admin_enabled"]:
        print("\n  Login en la API: usar identifier = user o email (según Aegis).\n")
    print()


if __name__ == "__main__":
    seed()
    client.close()
