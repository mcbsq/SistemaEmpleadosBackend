from flask import Flask

from api.tenants.registration import normalize_slug, register_tenant
from core.public_rate_limit import RegistrationRateLimiter
from tests.fakes import FakeMongo


class FakeProvisioner:
    def __init__(self): self.calls = []
    def provision(self, **data):
        self.calls.append(data)
        return {"tenant_id": data["slug"], "user_id": "aegis-1"}


def test_normalizes_company_slug():
    assert normalize_slug("  Mi Compañía  ") == "mi-compania"


def test_registration_creates_active_tenant_without_password():
    app = Flask(__name__)
    mongo = FakeMongo()
    provider = FakeProvisioner()
    payload = {"company_name": "Mi Compañía", "slug": "mi-compania", "admin_name": "Ana Pérez", "admin_email": "ana@example.com", "password": "segura-por-12-caracteres"}
    with app.app_context():
        body, status = register_tenant(mongo, payload, provider)
    assert status == 201
    assert body["slug"] == "mi-compania"
    assert mongo.db.tenants.find_one({"org_id": "mi-compania"})["estado"] == "active"
    admin = mongo.db.usuario.find_one({"org_id": "mi-compania"})
    assert admin["role"] == "SUPER_ADMIN"
    assert "password" not in admin


def test_rate_limiter_blocks_after_configured_limit():
    limiter = RegistrationRateLimiter(max_attempts=2, window_seconds=60)
    assert limiter.allow("198.51.100.10") is True
    assert limiter.allow("198.51.100.10") is True
    assert limiter.allow("198.51.100.10") is False


def test_reserved_slug_is_rejected_without_calling_identity_provider():
    app = Flask(__name__)
    provider = FakeProvisioner()
    with app.app_context():
        body, status = register_tenant(FakeMongo(), {
            "company_name": "API", "slug": "api", "admin_name": "Ana",
            "admin_email": "ana@example.com", "password": "segura-por-12-caracteres",
        }, provider)
    assert status == 400
    assert body["error"] == "invalid_registration"
    assert provider.calls == []
