# tests/test_perfil_ajustes.py
# Ajustes de perfil: el empleado cambia SU foto, nombre para mostrar y
# titular; nunca los de otro (salvo RH). El nombre legal no se toca aquí.
from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.perfil.routes import setup_perfil_routes
from tests.fakes import FakeMongo

FOTO = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="


def make_client(role, empleado_id):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    setup_perfil_routes(app, mongo)
    with app.app_context():
        token = create_access_token(identity="u", additional_claims={"role": role, "empleado_id": empleado_id})
    return app.test_client(), {"Authorization": f"Bearer {token}"}, mongo


def test_empleado_actualiza_su_propio_perfil():
    eid = ObjectId()
    client, h, mongo = make_client("EMPLOYEE", str(eid))
    mongo.db.empleados.insert_one({"_id": eid, "Nombre": "Ana", "ApelPaterno": "Ruiz"})
    r = client.patch(f"/perfil/{eid}/ajustes", headers=h,
                     json={"NombrePreferido": "  Anita  ", "Titular": "Frontend", "Fotografia": FOTO, "Nombre": "Hack"})
    assert r.status_code == 200
    doc = mongo.db.empleados.find_one({"_id": eid})
    assert doc["NombrePreferido"] == "Anita" and doc["Fotografias"] == [FOTO]
    assert doc["Nombre"] == "Ana"  # el nombre legal no se puede cambiar por aquí


def test_empleado_no_cambia_el_perfil_de_otro():
    eid, otro = ObjectId(), ObjectId()
    client, h, mongo = make_client("EMPLOYEE", str(eid))
    mongo.db.empleados.insert_one({"_id": otro, "Nombre": "Luis"})
    assert client.patch(f"/perfil/{otro}/ajustes", headers=h, json={"Titular": "x"}).status_code == 403


def test_rechaza_foto_que_no_es_imagen():
    eid = ObjectId()
    client, h, mongo = make_client("EMPLOYEE", str(eid))
    mongo.db.empleados.insert_one({"_id": eid, "Nombre": "Ana"})
    r = client.patch(f"/perfil/{eid}/ajustes", headers=h, json={"Fotografia": "data:text/html;base64,PHNjcmlwdD4="})
    assert r.status_code == 400 and "Fotografia" in r.get_json()["campos"]
