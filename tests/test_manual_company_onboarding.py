from flask import Flask, g

from api.org.logic import get_config
from api.login.logic import login
from api.tenants.logic import crear_tenant_manual, enviar_acceso_tenant_manual
from api.usuario.logic import create_usuario
from core.mailer import build_tenant_login_url, send_temp_password_email
from tests.fakes import FakeMongo


def test_slug_is_available_before_first_local_user(monkeypatch):
    monkeypatch.setenv("AEGIS_TENANT_ID", "cibercom")
    mongo = FakeMongo()
    mongo.db.raw.tenants.insert_one({
        "org_id": "herramientas-y-moldes-industriales",
        "nombre": "Herramientas y moldes industriales",
        "estado": "active",
    })

    app = Flask(__name__)
    with app.app_context():
        response, status = get_config(mongo, "herramientas-y-moldes-industriales")

    assert status == 200
    assert response.get_json()["existe"] is True
    assert mongo.db.raw.usuario.count_documents({"org_id": "herramientas-y-moldes-industriales"}) == 0


def test_inactive_company_slug_is_not_available(monkeypatch):
    monkeypatch.setenv("AEGIS_TENANT_ID", "cibercom")
    mongo = FakeMongo()
    mongo.db.raw.tenants.insert_one({
        "org_id": "empresa-suspendida",
        "estado": "suspendido",
    })

    app = Flask(__name__)
    with app.app_context():
        response, _ = get_config(mongo, "empresa-suspendida")

    assert response.get_json()["existe"] is False


def test_tenant_login_url_uses_configured_public_origin(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://rh.example.com/")

    assert build_tenant_login_url("mi-empresa") == "https://rh.example.com/mi-empresa"


def test_temp_password_email_includes_company_login_url(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def starttls(self): pass
        def login(self, *_args): pass
        def send_message(self, message): sent.append(message)

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM", "accesos@example.com")
    monkeypatch.setattr("core.mailer.smtplib.SMTP", FakeSMTP)

    assert send_temp_password_email(
        "admin@example.com",
        "admin",
        "temporal-segura",
        login_url="https://cibercomrh.com/mi-empresa",
    ) is True
    assert "https://cibercomrh.com/mi-empresa" in sent[0].get_content()


def test_creating_admin_sends_tenant_specific_link(monkeypatch):
    delivered = {}
    monkeypatch.setattr("api.usuario.logic.get_aegis_settings", lambda: {
        "login_enabled": True, "admin_enabled": True,
    })
    monkeypatch.setattr(
        "api.usuario.logic.aegis_admin_create_user",
        lambda *_args, **_kwargs: ({"id": "aegis-admin-1", "temp_password": "temporal"}, None),
    )

    def capture_email(email, user, password, login_url=None):
        delivered.update(email=email, user=user, password=password, login_url=login_url)
        return True

    monkeypatch.setattr("api.usuario.logic.send_temp_password_email", capture_email)
    app = Flask(__name__)
    with app.test_request_context():
        g.org_id = "herramientas-y-moldes-industriales"
        response, status = create_usuario(
            FakeMongo(), "bianca", None, None,
            role="SUPER_ADMIN", email="bianca@example.com",
        )

    assert status == 201
    assert delivered["login_url"] == "https://cibercomrh.com/herramientas-y-moldes-industriales"
    assert response.get_json()["login_url"] == delivered["login_url"]


def test_manual_company_bootstrap_creates_empty_active_workspace(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://cibercomrh.com")
    mongo = FakeMongo()

    body, status = crear_tenant_manual(mongo, {
        "nombre": "Herramientas y moldes industriales",
        "org_id": "herramientas-y-moldes-industriales",
        "contacto_nombre": "Blanca Mendoza",
        "contacto_email": "bianca@example.com",
    })

    assert status == 201
    assert body["login_url"] == "https://cibercomrh.com/herramientas-y-moldes-industriales"
    assert mongo.db.raw.tenants.find_one({"org_id": body["org_id"]})["estado"] == "activo"
    assert mongo.db.raw.usuario.count_documents({"org_id": body["org_id"]}) == 0
    assert mongo.db.raw.empleados.count_documents({"org_id": body["org_id"]}) == 0


def test_manual_company_bootstrap_rejects_duplicate_slug():
    mongo = FakeMongo()
    mongo.db.raw.tenants.insert_one({"org_id": "empresa-existente", "estado": "activo"})

    body, status = crear_tenant_manual(mongo, {
        "nombre": "Otra empresa",
        "org_id": "empresa-existente",
        "contacto_nombre": "Ana",
        "contacto_email": "ana@example.com",
    })

    assert status == 409
    assert body["error"] == "slug_unavailable"


def test_operator_can_email_first_admin_credentials_without_storing_password(monkeypatch):
    mongo = FakeMongo()
    mongo.db.raw.tenants.insert_one({
        "org_id": "mi-empresa", "estado": "activo",
        "contacto_email": "admin@example.com",
    })
    delivered = {}
    monkeypatch.setattr(
        "api.tenants.logic.send_temp_password_email",
        lambda email, user, password, login_url=None: delivered.update(
            email=email, user=user, password=password, login_url=login_url,
        ) is None,
    )

    body, status = enviar_acceso_tenant_manual(mongo, "mi-empresa", {
        "usuario": "admin@example.com",
        "temp_password": "temporal-generada-en-aegis",
    })

    assert status == 200
    assert body["email_sent"] is True
    assert delivered["login_url"].endswith("/mi-empresa")
    assert "temp_password" not in mongo.db.raw.tenants.find_one({"org_id": "mi-empresa"})


def test_slug_login_bypasses_ambiguous_email_resolution(monkeypatch):
    calls = {}
    monkeypatch.setattr("api.login.logic.get_aegis_settings", lambda: {
        "login_enabled": True, "tenant_id": "cibercom", "app_id": "empleados",
        "legacy_app_id": "principal", "legacy_fallback": False,
    })
    monkeypatch.setattr(
        "api.login.logic.aegis_resolve_tenant",
        lambda *_args: (_ for _ in ()).throw(AssertionError("no debe resolver por correo")),
    )
    def reject_login(identifier, password, tenant_id=None, app_id=None):
        calls.update(identifier=identifier, tenant_id=tenant_id, app_id=app_id)
        return None, ({"error": "invalid"}, 401)
    monkeypatch.setattr("api.login.logic.aegis_password_login", reject_login)

    app = Flask(__name__)
    with app.test_request_context():
        response, status = login(
            FakeMongo(), "admin@example.com", "incorrecta",
            requested_org_id="mi-empresa",
        )

    assert status == 401
    assert calls == {
        "identifier": "admin@example.com", "tenant_id": "mi-empresa", "app_id": "empleados",
    }
