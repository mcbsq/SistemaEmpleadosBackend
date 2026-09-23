# tests/test_session_duration.py
#
# La duración de sesión (vida del JWT) era un solo valor fijo global
# (JWT_ACCESS_MINUTES, 15 min) para TODAS las empresas — pedido explícito
# del cliente (2026-09-23): cada empresa decide su propio criterio de
# seguridad vía Configuración → Identidad → Sesión (org.sessionMinutes).
from datetime import timedelta

from flask import Flask

from api.org.logic import get_session_minutes, DEFAULT_CONFIG
from api.login.logic import login
from tests.fakes import FakeMongo


def test_get_session_minutes_defaults_when_unset():
    mongo = FakeMongo()
    assert get_session_minutes(mongo, "una-empresa-sin-configurar") == DEFAULT_CONFIG["sessionMinutes"]


def test_get_session_minutes_reads_the_orgs_own_value():
    mongo = FakeMongo()
    mongo.db.organizacion.insert_one({"org_id": "herramientas-y-moldes-industriales", "sessionMinutes": 120})
    assert get_session_minutes(mongo, "herramientas-y-moldes-industriales") == 120


def test_get_session_minutes_clamps_out_of_range_values():
    mongo = FakeMongo()
    mongo.db.organizacion.insert_one({"org_id": "muy-generosa", "sessionMinutes": 99999})
    mongo.db.organizacion.insert_one({"org_id": "muy-agresiva", "sessionMinutes": 1})
    assert get_session_minutes(mongo, "muy-generosa") == 1440
    assert get_session_minutes(mongo, "muy-agresiva") == 5


def test_login_issues_a_token_with_the_orgs_configured_lifetime(monkeypatch):
    captured = {}
    monkeypatch.setattr("api.login.logic.get_aegis_settings", lambda: {"login_enabled": False})
    monkeypatch.setattr(
        "api.login.logic.create_access_token",
        lambda identity, additional_claims=None, expires_delta=None: (
            captured.update(expires_delta=expires_delta) or "fake-jwt"
        ),
    )

    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "bianca", "password": "$scrypt$test-hash-not-checked",
        "role": "SUPER_ADMIN", "org_id": "herramientas-y-moldes-industriales",
    })
    mongo.db.organizacion.insert_one({"org_id": "herramientas-y-moldes-industriales", "sessionMinutes": 90})
    monkeypatch.setattr("api.login.logic.check_password_hash", lambda stored, pw: True)

    app = Flask(__name__)
    with app.test_request_context():
        login(mongo, "bianca", "cualquiera")

    assert captured["expires_delta"] == timedelta(minutes=90)
