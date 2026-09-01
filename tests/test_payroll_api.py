from flask import Flask, g
from flask_jwt_extended import JWTManager, create_access_token

from api.payroll.routes import setup_payroll_routes
from tests.fakes import FakeMongo


class RecordingProvider:
    def __init__(self): self.tenant = None; self.filters = None
    def list_payrolls(self, filters, tenant):
        self.tenant, self.filters = tenant, filters
        return {"configured": True, "items": [], "page": filters["page"], "page_size": filters["page_size"], "total": 0}


def make_client(role="ADMIN", provider=None):
    app = Flask(__name__); app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"; JWTManager(app)
    app.config["PAYROLL_PROVIDER"] = provider
    @app.before_request
    def tenant(): g.org_id = "empresa-a"
    setup_payroll_routes(app, FakeMongo())
    with app.app_context(): token = create_access_token(identity="user", additional_claims={"role": role, "org_id": "empresa-a"})
    return app.test_client(), token


def test_unconfigured_provider_returns_empty_contract():
    client, token = make_client()
    response = client.get("/payrolls", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json() == {"configured": False, "items": [], "page": 1, "page_size": 25, "total": 0}


def test_employee_cannot_list_company_payroll():
    client, token = make_client(role="EMPLOYEE")
    assert client.get("/payrolls", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_provider_receives_tenant_and_filters():
    provider = RecordingProvider(); client, token = make_client(provider=provider)
    response = client.get("/payrolls?status=paid&page=2&page_size=10", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert provider.tenant == "empresa-a"
    assert provider.filters["status"] == "paid"
    assert provider.filters["page"] == 2
