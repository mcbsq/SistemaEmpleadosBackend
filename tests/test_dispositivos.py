# tests/test_dispositivos.py
# Dispositivos de confianza ("entrar con Face ID / huella" en la app):
# registrar el celular, entrar con su llave, rotación de la llave y revocación.
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, decode_token

from api.dispositivos.routes import setup_dispositivos_routes
from tests.fakes import FakeMongo


def _app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({"user": "ana", "role": "EMPLOYEE", "empleado_id": "e1", "org_id": "acme"})
    setup_dispositivos_routes(app, mongo)
    return app, mongo


def _h(app, user="ana", role="EMPLOYEE", org="acme"):
    with app.app_context():
        t = create_access_token(identity=user, additional_claims={"user": user, "role": role, "org_id": org, "empleado_id": "e1"})
    return {"Authorization": f"Bearer {t}"}


def test_registrar_entrar_y_la_llave_rota():
    app, mongo = _app()
    c = app.test_client()
    r = c.post("/dispositivos", json={"nombre": "iPhone de Ana", "plataforma": "ios"}, headers=_h(app))
    assert r.status_code == 201
    d = r.get_json()
    # En la base solo queda el hash, nunca la llave.
    guardado = mongo.db.dispositivos.find_one({})
    assert d["llave"] not in str(guardado)

    r = c.post("/login/dispositivo", json={"dispositivo_id": d["dispositivo_id"], "llave": d["llave"]})
    assert r.status_code == 200
    cuerpo = r.get_json()
    with app.app_context():
        claims = decode_token(cuerpo["access_token"])
    assert claims["user"] == "ana" and claims["org_id"] == "acme" and claims["role"] == "EMPLOYEE"
    assert cuerpo["llave"] and cuerpo["llave"] != d["llave"]

    # La llave vieja ya no sirve (rotó); la nueva sí.
    assert c.post("/login/dispositivo", json={"dispositivo_id": d["dispositivo_id"], "llave": d["llave"]}).status_code == 401
    assert c.post("/login/dispositivo", json={"dispositivo_id": d["dispositivo_id"], "llave": cuerpo["llave"]}).status_code == 200


def test_llave_incorrecta_o_dispositivo_inventado():
    app, _ = _app()
    c = app.test_client()
    d = c.post("/dispositivos", json={}, headers=_h(app)).get_json()
    assert c.post("/login/dispositivo", json={"dispositivo_id": d["dispositivo_id"], "llave": "otra"}).status_code == 401
    assert c.post("/login/dispositivo", json={"dispositivo_id": "no-es-un-id", "llave": d["llave"]}).status_code == 401


def test_cerrar_sesion_desvincula_el_celular():
    app, _ = _app()
    c = app.test_client()
    d = c.post("/dispositivos", json={}, headers=_h(app)).get_json()
    assert len(c.get("/dispositivos", headers=_h(app)).get_json()) == 1
    assert c.delete(f"/dispositivos/{d['dispositivo_id']}", headers=_h(app)).status_code == 200
    assert c.get("/dispositivos", headers=_h(app)).get_json() == []
    assert c.post("/login/dispositivo", json={"dispositivo_id": d["dispositivo_id"], "llave": d["llave"]}).status_code == 401


def test_cuenta_borrada_ya_no_entra():
    app, mongo = _app()
    c = app.test_client()
    d = c.post("/dispositivos", json={}, headers=_h(app)).get_json()
    mongo.db.usuario.delete_one({"user": "ana"})
    assert c.post("/login/dispositivo", json={"dispositivo_id": d["dispositivo_id"], "llave": d["llave"]}).status_code == 401
