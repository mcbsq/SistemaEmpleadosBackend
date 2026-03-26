"""
seed.py — Cuentas maestras de prueba
Cibercom Sistema de Empleados 2026

Uso:
    python seed.py

Crea 3 empleados y sus cuentas de usuario para probar los 3 roles.
Es seguro ejecutarlo varias veces — verifica antes de insertar.
"""

from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from datetime import datetime

# ─── Conexión ────────────────────────────────────────────────────────────────
MONGO_URI = "mongodb+srv://cibercom:proyectos2022@cluster0.ilngp.mongodb.net/controlempleados?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db     = client["controlempleados"]

# ─── Cuentas a crear ─────────────────────────────────────────────────────────
CUENTAS = [
    {
        "user":     "superadmin_test",
        "password": "Super@2026",
        "role":     "SUPER_ADMIN",
        "empleado": {
            "Nombre":       "Super",
            "ApelPaterno":  "Admin",
            "ApelMaterno":  "Test",
            "FecNacimiento":"1985-01-01",
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
            "FecNacimiento":"1990-05-15",
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
            "FecNacimiento":"1995-08-20",
            "Fotografias":  [],
            "depto_id":     "TECH",
            "Cargo":        "Desarrollador",
        },
    },
]

def seed():
    print("\n=== SEED: Cuentas de prueba Cibercom ===\n")

    for cuenta in CUENTAS:
        user = cuenta["user"]
        role = cuenta["role"]

        # Verificar si ya existe
        existente = db.usuario.find_one({"user": user})
        if existente:
            print(f"  ⚠  '{user}' ya existe — omitiendo.")
            continue

        # 1. Crear empleado
        emp_data = {
            **cuenta["empleado"],
            "createdAt": datetime.utcnow(),
        }
        emp_result = db.empleados.insert_one(emp_data)
        empleado_id = str(emp_result.inserted_id)

        # 2. Crear registro RH básico con depto_id
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

        # 3. Crear usuario
        hashed = generate_password_hash(cuenta["password"])
        db.usuario.insert_one({
            "user":        user,
            "password":    hashed,
            "role":        role,
            "empleado_id": empleado_id,
        })

        print(f"  ✓  '{user}' creado")
        print(f"     Role:        {role}")
        print(f"     Password:    {cuenta['password']}")
        print(f"     Empleado ID: {empleado_id}")
        print(f"     Depto:       {cuenta['empleado']['depto_id']}\n")

    print("=== Resumen de cuentas disponibles ===\n")
    print("  Usuario           Contraseña       Rol")
    print("  ──────────────────────────────────────────────")
    for c in CUENTAS:
        print(f"  {c['user']:<18} {c['password']:<16} {c['role']}")
    print()

if __name__ == "__main__":
    seed()
    client.close()