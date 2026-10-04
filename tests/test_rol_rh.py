# tests/test_rol_rh.py
# Rol RH: hereda lo que una ruta permite a ADMIN (personas), nunca lo que es
# solo de SUPER_ADMIN (sistema). Y el panel de RH calcula sus KPIs.
from datetime import date, timedelta

from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.auth_decorators import require_roles, rol_permitido
from api.panel_rh.routes import setup_panel_rh_routes
from core.visibilidad_perfil import acceso_perfil
from tests.fakes import FakeMongo


def test_rh_cuenta_como_admin_pero_no_como_superadmin():
    assert rol_permitido("RH", ("ADMIN", "SUPER_ADMIN"))
    assert not rol_permitido("RH", ("SUPER_ADMIN",))
    assert not rol_permitido("EMPLOYEE", ("ADMIN", "SUPER_ADMIN"))


def test_rh_ve_y_edita_todo_el_perfil():
    a = acceso_perfil(FakeMongo(), {"role": "RH", "empleado_id": None}, str(ObjectId()))
    assert all(a["ver"].values()) and all(a["editar"].values())


def _client(role):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    setup_panel_rh_routes(app, mongo)

    @app.route("/solo-super")
    @require_roles("SUPER_ADMIN")
    def solo_super():
        return "ok"

    with app.app_context():
        t = create_access_token(identity="u", additional_claims={"role": role})
    return app.test_client(), {"Authorization": f"Bearer {t}"}, mongo


def test_panel_rh_kpis():
    c, h, mongo = _client("RH")
    completo, incompleto = ObjectId(), ObjectId()
    hoy = date.today()
    mongo.db.empleados.insert_one({"_id": completo, "Nombre": "Ana", "ApelPaterno": "Ruiz"})
    mongo.db.empleados.insert_one({"_id": incompleto, "Nombre": "Luis", "ApelPaterno": "Paz",
                                   "FecNacimiento": (hoy + timedelta(days=2)).replace(year=1990).isoformat()})
    mongo.db.rh.insert_one({"empleado_id": completo, "Puesto": "Dev", "FechaIngreso": hoy.replace(day=1).isoformat(),
                            "CURP": "X", "RFC": "X", "NSS": "X", "SalarioDiario": "500", "CLABE": "X"})
    mongo.db.personascontacto.insert_one({"empleadoid": completo, "Contactos": [{"nombreContacto": "Mamá"}]})
    mongo.db.vacaciones_solicitudes.insert_one({"empleado_id": completo, "estado": "aprobada",
                                                "fecha_inicio": hoy.isoformat(), "fecha_fin": hoy.isoformat(), "dias_solicitados": 1})
    mongo.db.solicitudes_rh.insert_one({"empleado_id": str(incompleto), "estado": "abierta", "asunto": "x", "creado_en": "2026"})

    d = c.get("/rh/panel", headers=h).get_json()
    k = d["kpis"]
    assert k["plantilla"] == 2 and k["altas_mes"] == 1 and k["fuera_hoy"] == 1
    assert k["expedientes_incompletos"] == 1 and k["solicitudes_pendientes"] == 1
    assert d["incompletos"][0]["nombre"] == "Luis Paz" and "CURP" in d["incompletos"][0]["faltan"]
    assert any(e["tipo"] == "cumpleanos" for e in d["eventos"])
    assert c.get("/solo-super", headers=h).status_code == 403


def test_empleado_no_ve_el_panel():
    c, h, _ = _client("EMPLOYEE")
    assert c.get("/rh/panel", headers=h).status_code == 403


def test_rh_crea_cuentas_de_empleado_pero_no_de_administrador(monkeypatch):
    from api.usuario import routes as usuario_routes
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    creados = []
    monkeypatch.setattr(usuario_routes, "usuario_existente", lambda *a, **k: False)
    monkeypatch.setattr(usuario_routes, "create_usuario",
                        lambda mongo, user, pw, eid, role, **kw: (creados.append((user, role, kw.get("areas_administradas"))) or ("ok", 201)))
    usuario_routes.setup_usuario_routes(app, FakeMongo())
    with app.app_context():
        t = create_access_token(identity="rh", additional_claims={"role": "RH"})
    h = {"Authorization": f"Bearer {t}"}
    c = app.test_client()
    assert c.post("/usuario", headers=h, json={"user": "nuevo", "role": "EMPLOYEE", "areas_administradas": ["x"]}).status_code == 201
    assert creados == [("nuevo", "EMPLOYEE", None)]
    for rol in ("ADMIN", "SUPER_ADMIN", "RH", "super_admin"):
        assert c.post("/usuario", headers=h, json={"user": "malo", "role": rol}).status_code == 403
