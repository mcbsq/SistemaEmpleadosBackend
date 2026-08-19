# tests/test_super_admin_sin_empleado.py
# ─────────────────────────────────────────────────────────────────────────────
# Regla de negocio: SUPER_ADMIN es una cuenta administrativa (de la empresa o
# de Cibercom), no una persona en la plantilla — nunca debe quedar vinculada
# a un empleado_id, para que (a) nunca aparezca en el Organigrama y (b) nunca
# sea dable de alta en la tabla de RH como si fuera personal real. Los roles
# operativos (ADMIN, EMPLOYEE, roles personalizados) y los empleados sin
# cuenta de login siguen sin ninguna restricción.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask

from tests.fakes import FakeMongo
from api.usuario.logic import create_usuario, update_usuario
from api.empleados.logic import get_empleados
import api.usuario.logic as usuario_logic


@pytest.fixture
def mongo():
    return FakeMongo()


@pytest.fixture(autouse=True)
def app_context():
    bare_app = Flask(__name__)
    with bare_app.app_context():
        yield


@pytest.fixture(autouse=True)
def modo_legacy(monkeypatch):
    """
    Estas pruebas usan FakeMongo y esperan el flujo legacy (hash en Mongo,
    sin Aegis) — sin esto, si el proceso de pytest ya importó `app.py` en
    otra prueba de este mismo run (ver test_integracion_multiempresa.py,
    que carga .env.local de verdad), get_aegis_settings() reflejaría el
    Aegis real y create_usuario exigiría email en vez de password. Se fuerza
    aquí explícitamente para que estas pruebas no dependan de qué otro
    archivo se haya importado antes en el mismo proceso.
    """
    monkeypatch.setattr(usuario_logic, "get_aegis_settings", lambda: {
        "login_enabled": False, "admin_enabled": False,
    })


def _empleado(mongo, **overrides):
    doc = {"Nombre": "Test", "ApelPaterno": "Empleado", "depto_id": "TECH", "estado": "activo"}
    doc.update(overrides)
    return mongo.db.empleados.insert_one(doc).inserted_id


# ── create_usuario ──────────────────────────────────────────────────────────

def test_create_usuario_super_admin_ignora_empleado_id(mongo):
    """Pedir un SUPER_ADMIN con empleado_id: el campo se ignora, no se guarda."""
    eid = _empleado(mongo)
    resp, status = create_usuario(mongo, "super1", "clave123", str(eid), role="SUPER_ADMIN")
    assert status == 201

    guardado = mongo.db.usuario.find_one({"user": "super1"})
    assert guardado["empleado_id"] is None


def test_create_usuario_admin_si_conserva_empleado_id(mongo):
    """Un ADMIN (rol operativo real) sí puede quedar vinculado a su empleado."""
    eid = _empleado(mongo)
    resp, status = create_usuario(mongo, "admin1", "clave123", str(eid), role="ADMIN")
    assert status == 201

    guardado = mongo.db.usuario.find_one({"user": "admin1"})
    assert guardado["empleado_id"] == eid


def test_create_usuario_employee_si_conserva_empleado_id(mongo):
    """Un EMPLOYEE también puede (y debe poder) quedar vinculado a su empleado."""
    eid = _empleado(mongo)
    resp, status = create_usuario(mongo, "empleado1", "clave123", str(eid), role="EMPLOYEE")
    assert status == 201

    guardado = mongo.db.usuario.find_one({"user": "empleado1"})
    assert guardado["empleado_id"] == eid


# ── update_usuario ──────────────────────────────────────────────────────────

def test_update_usuario_a_super_admin_limpia_empleado_id_existente(mongo):
    """Si a un ADMIN ya vinculado a un empleado se le sube el rol a SUPER_ADMIN,
    el vínculo se limpia — no debe quedar como dato legacy huérfano."""
    eid = _empleado(mongo)
    uid = mongo.db.usuario.insert_one({
        "user": "promovido", "role": "ADMIN", "empleado_id": eid,
    }).inserted_id

    resp, status = update_usuario(mongo, str(uid), role="SUPER_ADMIN")
    assert status == 200

    guardado = mongo.db.usuario.find_one({"_id": uid})
    assert guardado["empleado_id"] is None


def test_update_usuario_admin_no_toca_empleado_id(mongo):
    """Actualizar algo que no sea el rol no debe alterar el vínculo de un ADMIN."""
    eid = _empleado(mongo)
    uid = mongo.db.usuario.insert_one({
        "user": "admin2", "role": "ADMIN", "empleado_id": eid,
    }).inserted_id

    resp, status = update_usuario(mongo, str(uid), user="admin2-renombrado")
    assert status == 200

    guardado = mongo.db.usuario.find_one({"_id": uid})
    assert guardado["empleado_id"] == eid


# ── get_empleados (Organigrama / tabla RH) ──────────────────────────────────

def test_get_empleados_excluye_al_vinculado_con_super_admin(mongo):
    """Defensa en profundidad: aunque exista (por datos legacy) un empleado
    vinculado a una cuenta SUPER_ADMIN, no debe salir en el listado que
    alimenta el Organigrama y la tabla de RH."""
    eid_super = _empleado(mongo, Nombre="Cuenta", ApelPaterno="Administrativa")
    eid_normal = _empleado(mongo, Nombre="Persona", ApelPaterno="Real")

    mongo.db.usuario.insert_one({"user": "super_legacy", "role": "SUPER_ADMIN", "empleado_id": eid_super})
    mongo.db.usuario.insert_one({"user": "empleado_real", "role": "EMPLOYEE", "empleado_id": eid_normal})

    resp = get_empleados(mongo, identity={"role": "SUPER_ADMIN"})
    import json
    nombres = {e["Nombre"] for e in json.loads(resp.get_data(as_text=True))}

    assert "Cuenta" not in nombres
    assert "Persona" in nombres


def test_get_empleados_excluye_super_admin_con_empleado_id_guardado_como_string(mongo):
    """Caso real encontrado en producción: cuentas SUPER_ADMIN creadas antes
    de esta regla tienen empleado_id guardado como STRING en Mongo (no
    ObjectId). Si _empleado_ids_super_admin no normaliza el tipo, el $nin
    nunca hace match contra empleados._id (que sí es ObjectId) y el filtro
    queda como si no existiera."""
    eid_super = _empleado(mongo, Nombre="Cuenta", ApelPaterno="Administrativa")
    mongo.db.usuario.insert_one({
        "user": "super_legacy_string", "role": "SUPER_ADMIN",
        "empleado_id": str(eid_super),  # el caso real: string, no ObjectId
    })

    resp = get_empleados(mongo, identity={"role": "SUPER_ADMIN"})
    import json
    nombres = {e["Nombre"] for e in json.loads(resp.get_data(as_text=True))}

    assert "Cuenta" not in nombres


def test_get_empleados_incluye_empleados_sin_cuenta_de_login(mongo):
    """Un empleado real sin ninguna cuenta de usuario vinculada (caso normal:
    headcount sin acceso al sistema) sigue apareciendo sin restricción nueva."""
    _empleado(mongo, Nombre="SinLogin")

    resp = get_empleados(mongo, identity={"role": "SUPER_ADMIN"})
    import json
    nombres = {e["Nombre"] for e in json.loads(resp.get_data(as_text=True))}

    assert "SinLogin" in nombres
