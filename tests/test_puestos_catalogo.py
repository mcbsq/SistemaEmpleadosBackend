# tests/test_puestos_catalogo.py
# Área y puesto se eligen del catálogo (Configuración → Áreas): el empleado
# puede cambiar los suyos, pero solo a un puesto que exista en esa área.
from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.catalogodepto.logic import normalizar_puestos
from api.catalogodepto.routes import setup_catalogodepto_routes
from tests.fakes import FakeMongo


def _h(app, role, empleado_id=None, user="u"):
    with app.app_context():
        t = create_access_token(identity=user, additional_claims={"role": role, "user": user, "empleado_id": empleado_id})
    return {"Authorization": f"Bearer {t}"}


def test_normaliza_puestos():
    assert normalizar_puestos(["  Desarrollador  web ", "desarrollador WEB", "", None, "QA"]) == ["Desarrollador web", "QA"]


def _app_rh():
    from api.rh.routes import setup_rh_routes
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    setup_catalogodepto_routes(app, mongo)
    setup_rh_routes(app, mongo)
    return app, mongo


def test_rh_define_puestos_y_asigna_desde_la_ficha_laboral():
    app, mongo = _app_rh()
    c = app.test_client()
    area_id = mongo.db.catalogodepto.insert_one({"NombreDepto": "TECH", "DeptoPadre": None}).inserted_id
    emp = mongo.db.empleados.insert_one({"Nombre": "Ana", "ApelPaterno": "Ruiz", "depto_id": "Sin Asignar"}).inserted_id

    assert c.put(f"/catalogodepto/{area_id}/puestos", json={"Puestos": ["Dev", "QA"]},
                 headers=_h(app, "EMPLOYEE", str(emp))).status_code == 403
    assert c.put(f"/catalogodepto/{area_id}/puestos", json={"Puestos": ["Dev", "QA"]},
                 headers=_h(app, "RH")).get_json()["Puestos"] == ["Dev", "QA"]

    rh = _h(app, "RH")
    r = c.put(f"/rh/{emp}", json={"Departamento": "TECH", "Puesto": "Inventado"}, headers=rh)
    assert r.status_code == 400 and "Puesto" in r.get_json()["campos"]

    assert c.put(f"/rh/{emp}", json={"Departamento": "TECH", "Puesto": "QA"}, headers=rh).status_code == 200
    assert mongo.db.empleados.find_one({"_id": emp})["depto_id"] == "TECH"
    assert mongo.db.rh.find_one({"empleado_id": emp})["Puesto"] == "QA"


def test_empleado_no_cambia_su_puesto():
    app, mongo = _app_rh()
    c = app.test_client()
    mongo.db.catalogodepto.insert_one({"NombreDepto": "TECH", "Puestos": ["QA"]})
    emp = mongo.db.empleados.insert_one({"Nombre": "Ana"}).inserted_id
    r = c.put(f"/rh/{emp}", json={"Departamento": "TECH", "Puesto": "QA"}, headers=_h(app, "EMPLOYEE", str(emp)))
    assert r.status_code == 403
