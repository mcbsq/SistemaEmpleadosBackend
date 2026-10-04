# tests/test_vacaciones_doble_aprobacion.py
# Doble visto bueno de vacaciones: el jefe directo (según la ficha laboral) y
# RH/Administración. La solicitud solo queda aprobada con ambos; un rechazo de
# cualquiera la cierra. Sin jefe asignado basta con RH.
from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.vacaciones.routes import setup_vacaciones_routes
from tests.fakes import FakeMongo


def _app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    setup_vacaciones_routes(app, mongo)
    return app, mongo


def _h(app, user, role, empleado_id=None):
    with app.app_context():
        t = create_access_token(identity=user, additional_claims={"role": role, "user": user, "empleado_id": empleado_id})
    return {"Authorization": f"Bearer {t}"}


def _equipo(mongo, con_jefe=True):
    emp, jefe = ObjectId(), ObjectId()
    mongo.db.empleados.insert_one({"_id": emp, "Nombre": "Ana", "ApelPaterno": "Ruiz"})
    mongo.db.empleados.insert_one({"_id": jefe, "Nombre": "Luis", "ApelPaterno": "Paz"})
    if con_jefe:
        mongo.db.rh.insert_one({"empleado_id": emp, "JefeInmediato_id": str(jefe)})
    return str(emp), str(jefe)


def _solicitar(c, app, emp):
    r = c.post("/vacaciones", json={"fecha_inicio": "2026-11-02", "fecha_fin": "2026-11-04"},
               headers=_h(app, "ana", "EMPLOYEE", emp))
    assert r.status_code == 201
    return r.get_json()["_id"]


def test_requiere_jefe_y_rh_en_cualquier_orden():
    app, mongo = _app()
    c = app.test_client()
    emp, jefe = _equipo(mongo)
    sid = _solicitar(c, app, emp)

    # El jefe ve la solicitud de su equipo; un compañero cualquiera no.
    assert len(c.get("/vacaciones/pendientes", headers=_h(app, "luis", "JEFE_AREA", jefe)).get_json()) == 1
    assert c.get("/vacaciones/pendientes", headers=_h(app, "otro", "EMPLOYEE", str(ObjectId()))).get_json() == []

    r = c.patch(f"/vacaciones/{sid}/estado", json={"estado": "aprobada"}, headers=_h(app, "rh", "RH"))
    assert r.get_json()["estado"] == "pendiente"
    # RH no puede dar dos veces su visto bueno ni el del jefe.
    assert c.patch(f"/vacaciones/{sid}/estado", json={"estado": "aprobada"}, headers=_h(app, "rh", "RH")).status_code == 403

    r = c.patch(f"/vacaciones/{sid}/estado", json={"estado": "aprobada"}, headers=_h(app, "luis", "JEFE_AREA", jefe))
    assert r.get_json()["estado"] == "aprobada"
    assert mongo.db.vacaciones_solicitudes.find_one({"_id": ObjectId(sid)})["estado"] == "aprobada"


def test_rechazo_del_jefe_cierra_la_solicitud():
    app, mongo = _app()
    c = app.test_client()
    emp, jefe = _equipo(mongo)
    sid = _solicitar(c, app, emp)
    r = c.patch(f"/vacaciones/{sid}/estado", json={"estado": "rechazada"}, headers=_h(app, "luis", "JEFE_AREA", jefe))
    assert r.get_json()["estado"] == "rechazada"


def test_sin_jefe_asignado_basta_rh():
    app, mongo = _app()
    c = app.test_client()
    emp, _ = _equipo(mongo, con_jefe=False)
    sid = _solicitar(c, app, emp)
    r = c.patch(f"/vacaciones/{sid}/estado", json={"estado": "aprobada"}, headers=_h(app, "admin", "ADMIN"))
    assert r.get_json()["estado"] == "aprobada"


def test_solo_el_jefe_directo_da_el_primer_visto_bueno():
    app, mongo = _app()
    c = app.test_client()
    emp, _ = _equipo(mongo)
    sid = _solicitar(c, app, emp)
    otro_jefe = _h(app, "pepe", "JEFE_AREA", str(ObjectId()))
    assert c.patch(f"/vacaciones/{sid}/estado", json={"estado": "aprobada"}, headers=otro_jefe).status_code == 403
