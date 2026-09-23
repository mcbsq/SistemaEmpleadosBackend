# tests/test_change_password_tenant_scoping.py
#
# Regresión real (2026-09-23): POST /change-password siempre re-validaba la
# contraseña actual contra el tenant estático "cibercom" en Aegis, sin
# importar la empresa real de la cuenta. Para cualquier usuario de una
# empresa cliente que no fuera cibercom, Aegis respondía 401 (el identifier
# no existe en cibercom) y el backend lo traducía como "la contraseña que
# escribiste no es correcta" — un mensaje falso: la contraseña estaba bien,
# el tenant era el equivocado. Reventaba justo en el primer inicio de
# sesión (definir contraseña desde la temporal), el momento más visible
# posible para un cliente nuevo.
#
# Caso real que lo expuso: la cuenta de Herramientas y Moldes Industriales
# (biancamendoza75@yahoo.com.mx) no pudo completar su alta por esto.
from flask import Flask

from api.login.logic import change_password
from tests.fakes import FakeMongo


def _aegis_settings_stub(**overrides):
    base = {"login_enabled": True, "tenant_id": "cibercom", "app_id": "empleados"}
    base.update(overrides)
    return lambda: base


def test_change_password_uses_the_users_real_tenant(monkeypatch):
    captured = {}
    monkeypatch.setattr("api.login.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.login.logic.aegis_change_password",
        lambda identifier, current, new, tenant_id=None, app_id=None: (
            captured.update(identifier=identifier, tenant_id=tenant_id) or None
        ),
    )

    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "bianca", "email": "bianca@example.com",
        "org_id": "herramientas-y-moldes-industriales",
        "aegis_user_id": "aegis-1",
    })

    app = Flask(__name__)
    with app.test_request_context():
        response, status = change_password(
            mongo, {"user": "bianca"}, "temporal-actual", "NuevaContrasena123!",
        )

    assert status == 200
    assert captured["tenant_id"] == "herramientas-y-moldes-industriales"
    assert captured["identifier"] == "bianca@example.com"


def test_change_password_wrong_tenant_still_surfaces_a_clear_401(monkeypatch):
    """Si Aegis de verdad rechaza la contraseña (tenant correcto, clave mala),
    el mensaje al usuario debe seguir siendo el mismo de siempre."""
    monkeypatch.setattr("api.login.logic.get_aegis_settings", _aegis_settings_stub())
    monkeypatch.setattr(
        "api.login.logic.aegis_change_password",
        lambda *a, **k: ({"error": "invalid"}, 401),
    )

    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "bianca", "email": "bianca@example.com",
        "org_id": "herramientas-y-moldes-industriales",
        "aegis_user_id": "aegis-1",
    })

    app = Flask(__name__)
    with app.test_request_context():
        response, status = change_password(
            mongo, {"user": "bianca"}, "contraseña-incorrecta", "NuevaContrasena123!",
        )

    assert status == 401
    assert "no es correcta" in response.get_json()["error"]
