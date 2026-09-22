# tests/test_aegis_admin_tenant_scoping.py
#
# Regresión real (2026-09-22): las operaciones admin de Aegis (crear usuario,
# listar, resetear contraseña, desactivar) mandaban SIEMPRE el tenant estático
# "cibercom" en X-Tenant-Id, sin importar de qué empresa era el usuario sobre
# el que se operaba. Para cualquier empresa cliente que no fuera cibercom,
# esto significaba operar sobre el tenant equivocado en Aegis (404/401 desde
# Aegis, o — peor — crear la identidad bajo el tenant incorrecto).
#
# Caso real que expuso el bug: al dar de alta el admin de "Herramientas y
# moldes industriales" dos veces con una variante de slug distinta
# (herramientas_y_moldes_industriales vs herramientas-y-moldes-industriales),
# Aegis terminó con dos identidades para el mismo correo — el login
# subsecuente daba "tu cuenta pertenece a más de una empresa". Estas pruebas
# no cubren ESE duplicado (es un problema de datos, no de código), pero sí
# fijan que de aquí en adelante toda llamada admin usa el tenant REAL
# (g.org_id) en vez de uno fijo, para que operar sobre la cuenta de una
# empresa cliente no dependa de que además tenga el tenant "cibercom".
from flask import Flask, g

from api.usuario.logic import create_usuario, get_usuarios, delete_usuario, update_usuario
from tests.fakes import FakeMongo


def _aegis_settings_stub(**overrides):
    base = {"login_enabled": True, "admin_enabled": True, "app_id": "empleados", "tenant_id": "cibercom"}
    base.update(overrides)
    return lambda: base


def test_create_usuario_rejects_an_email_already_used_by_another_company(monkeypatch):
    """
    La invariante real: un correo pertenece a UNA sola empresa. Esta prueba
    reproduce exactamente el caso de producción — un segundo intento de alta
    para el mismo correo bajo un org_id distinto (una variante de slug
    corregida sin borrar la primera) debe rechazarse ANTES de llamar a Aegis,
    no crear una segunda identidad duplicada.
    """
    aegis_calls = []
    monkeypatch.setattr("api.usuario.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.usuario.logic.aegis_admin_create_user",
        lambda *a, **k: (aegis_calls.append((a, k)) or ({"id": "aegis-2", "temp_password": "x"}, None)),
    )
    monkeypatch.setattr("api.usuario.logic.send_temp_password_email", lambda *a, **k: True)

    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "org_id": "herramientas_y_moldes_industriales",
        "user": "bianca", "email": "bianca@example.com",
        "role": "SUPER_ADMIN", "aegis_user_id": "aegis-1",
    })

    app = Flask(__name__)
    with app.test_request_context():
        g.org_id = "herramientas-y-moldes-industriales"
        response, status = create_usuario(
            mongo, "bianca", None, None,
            role="SUPER_ADMIN", email="bianca@example.com",
        )

    assert status == 409
    assert "otra empresa" in response.get_json()["error"]
    assert aegis_calls == []  # nunca debió intentar crear la segunda identidad en Aegis


def test_create_usuario_allows_same_email_reused_within_the_same_company(monkeypatch):
    """El chequeo es cross-empresa, no debe bloquear un alta legítima dentro
    de la MISMA empresa (ej. recrear tras un borrado previo)."""
    monkeypatch.setattr("api.usuario.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.usuario.logic.aegis_admin_create_user",
        lambda *a, **k: ({"id": "aegis-1", "temp_password": "x"}, None),
    )
    monkeypatch.setattr("api.usuario.logic.send_temp_password_email", lambda *a, **k: True)

    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "org_id": "herramientas-y-moldes-industriales",
        "user": "otro", "email": "bianca@example.com",
        "role": "EMPLOYEE", "aegis_user_id": "aegis-0",
    })

    app = Flask(__name__)
    with app.test_request_context():
        g.org_id = "herramientas-y-moldes-industriales"
        response, status = create_usuario(
            mongo, "bianca2", None, None,
            role="SUPER_ADMIN", email="bianca@example.com",
        )

    assert status == 201


def test_create_usuario_sends_the_real_tenant_to_aegis(monkeypatch):
    captured = {}
    monkeypatch.setattr("api.usuario.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.usuario.logic.aegis_admin_create_user",
        lambda email, role="empleado", tenant_id=None: (
            captured.update(email=email, role=role, tenant_id=tenant_id) or
            ({"id": "aegis-1", "temp_password": "temporal"}, None)
        ),
    )
    monkeypatch.setattr("api.usuario.logic.send_temp_password_email", lambda *a, **k: True)

    app = Flask(__name__)
    with app.test_request_context():
        g.org_id = "herramientas-y-moldes-industriales"
        response, status = create_usuario(
            FakeMongo(), "bianca", None, None,
            role="SUPER_ADMIN", email="bianca@example.com",
        )

    assert status == 201
    assert captured["tenant_id"] == "herramientas-y-moldes-industriales"


def test_get_usuarios_enriches_from_the_real_tenant(monkeypatch):
    captured = {}
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "org_id": "herramientas-y-moldes-industriales",
        "user": "bianca", "email": "bianca@example.com",
        "role": "SUPER_ADMIN", "aegis_user_id": "aegis-1",
    })
    monkeypatch.setattr("api.usuario.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.usuario.logic.aegis_admin_list_users",
        lambda tenant_id=None: (captured.update(tenant_id=tenant_id) or ([], None)),
    )

    app = Flask(__name__)
    with app.test_request_context():
        g.org_id = "herramientas-y-moldes-industriales"
        get_usuarios(mongo)

    assert captured["tenant_id"] == "herramientas-y-moldes-industriales"


def test_reset_password_targets_the_real_tenant(monkeypatch):
    captured = {}
    mongo = FakeMongo()
    doc_id = mongo.db.usuario.insert_one({
        "org_id": "herramientas-y-moldes-industriales",
        "user": "bianca", "email": "bianca@example.com",
        "role": "SUPER_ADMIN", "aegis_user_id": "aegis-1",
    }).inserted_id

    monkeypatch.setattr("api.usuario.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.usuario.logic.aegis_admin_reset_password",
        lambda aegis_user_id, tenant_id=None: (captured.update(tenant_id=tenant_id) or ("temporal-nueva", None)),
    )

    app = Flask(__name__)
    with app.test_request_context():
        g.org_id = "herramientas-y-moldes-industriales"
        update_usuario(mongo, str(doc_id), password="cualquier-cosa")

    assert captured["tenant_id"] == "herramientas-y-moldes-industriales"


def test_delete_usuario_deactivates_on_the_real_tenant(monkeypatch):
    captured = {}
    mongo = FakeMongo()
    doc_id = mongo.db.usuario.insert_one({
        "org_id": "herramientas-y-moldes-industriales",
        "user": "bianca", "email": "bianca@example.com",
        "role": "SUPER_ADMIN", "aegis_user_id": "aegis-1",
    }).inserted_id

    monkeypatch.setattr("api.usuario.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.usuario.logic.aegis_admin_set_active",
        lambda aegis_user_id, is_active, tenant_id=None: captured.update(tenant_id=tenant_id, is_active=is_active),
    )

    app = Flask(__name__)
    with app.test_request_context():
        g.org_id = "herramientas-y-moldes-industriales"
        delete_usuario(mongo, str(doc_id))

    assert captured["tenant_id"] == "herramientas-y-moldes-industriales"
    assert captured["is_active"] is False
