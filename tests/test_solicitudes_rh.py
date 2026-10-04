# tests/test_solicitudes_rh.py
# El empleado escribe a RH desde su perfil; RH lo ve, responde y el empleado
# recibe aviso. Un empleado no puede ver ni contestar solicitudes de otros.
from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.solicitudes_rh.routes import setup_solicitudes_rh_routes
from tests.fakes import FakeMongo


def make_app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    setup_solicitudes_rh_routes(app, mongo)
    return app, mongo


def token(app, user, role, empleado_id=None):
    with app.app_context():
        t = create_access_token(identity=user, additional_claims={"user": user, "role": role, "empleado_id": empleado_id})
    return {"Authorization": f"Bearer {t}"}


def test_flujo_completo_empleado_rh():
    app, mongo = make_app()
    c = app.test_client()
    eid = ObjectId()
    mongo.db.empleados.insert_one({"_id": eid, "Nombre": "Ana", "ApelPaterno": "Ruiz"})
    mongo.db.usuario.insert_one({"user": "rh1", "role": "ADMIN"})
    emp_h = token(app, "ana", "EMPLOYEE", str(eid))
    rh_h = token(app, "rh1", "ADMIN")

    r = c.post("/solicitudes-rh", headers=emp_h, json={"tipo": "correccion", "seccion": "laboral", "mensaje": "Mi CURP está mal escrita"})
    assert r.status_code == 201
    sid = r.get_json()["_id"]
    assert mongo.db.notificaciones.find_one({"usuario": "rh1", "tipo": "solicitud_rh"})

    assert c.get("/solicitudes-rh", headers=emp_h).status_code == 403
    assert len(c.get("/solicitudes-rh", headers=rh_h).get_json()) == 1
    assert c.patch(f"/solicitudes-rh/{sid}", headers=emp_h, json={"estado": "resuelta"}).status_code == 403

    r = c.patch(f"/solicitudes-rh/{sid}", headers=rh_h, json={"estado": "resuelta", "respuesta": "Listo, ya quedó"})
    assert r.status_code == 200 and r.get_json()["estado"] == "resuelta"
    assert mongo.db.notificaciones.find_one({"usuario": "ana", "tipo": "solicitud_rh_respuesta"})
    mias = c.get("/solicitudes-rh/mias", headers=emp_h).get_json()
    assert mias[0]["respuestas"][0]["texto"] == "Listo, ya quedó"


def test_valida_tipo_y_mensaje():
    app, mongo = make_app()
    c = app.test_client()
    h = token(app, "ana", "EMPLOYEE", str(ObjectId()))
    r = c.post("/solicitudes-rh", headers=h, json={"tipo": "inventado", "mensaje": "x"})
    assert r.status_code == 400 and {"tipo", "mensaje"} <= set(r.get_json()["campos"])
