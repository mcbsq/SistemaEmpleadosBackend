# tests/test_contrasena_temporal_cuentas.py
#
# Al dar de alta una cuenta, la temporal de Aegis siempre vuelve a quien la
# creó (pop-up) y queda cifrada para consultarla en Cuentas hasta que la
# persona la cambie. Si Aegis no deja generar otra temporal al restablecer
# (403), se le manda a la persona el enlace de recuperación de Aegis.
from flask import Flask, g

from api.usuario import logic
from core import temporal
from tests.fakes import FakeMongo


def _app():
    app = Flask(__name__)
    return app


def _aegis(monkeypatch, reset=("Temp-Nueva-1", None)):
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    monkeypatch.setattr(logic, "get_aegis_settings", lambda: {"login_enabled": True, "admin_enabled": True})
    monkeypatch.setattr(logic, "aegis_admin_create_user",
                        lambda email, role="empleado", tenant_id=None: ({"id": "a-1", "temp_password": "Temp-Alta-1"}, None))
    monkeypatch.setattr(logic, "aegis_admin_reset_password", lambda uid, tenant_id=None: reset)
    monkeypatch.setattr(logic, "send_temp_password_email", lambda *a, **k: True)
    monkeypatch.setattr(logic, "registrar_auditoria", lambda *a, **k: None)


def test_alta_devuelve_la_temporal_aunque_se_envie_por_correo_y_la_guarda_cifrada(monkeypatch):
    _aegis(monkeypatch)
    mongo = FakeMongo()
    with _app().test_request_context():
        g.org_id = "cibercom"
        resp, status = logic.create_usuario(mongo, "ana", None, None, "EMPLOYEE", email="ana@x.com")
    data = resp.get_json()
    assert status == 201 and data["temp_password"] == "Temp-Alta-1" and data["email_sent"] is True
    doc = mongo.db.usuario.find_one({"user": "ana"})
    assert "Temp-Alta-1" not in str(doc) and temporal.leer(doc) == "Temp-Alta-1"


def test_consultar_la_temporal_y_listado_sin_valor(monkeypatch):
    _aegis(monkeypatch)
    monkeypatch.setattr(logic, "aegis_admin_list_users", lambda tenant_id=None: ([], None))
    mongo = FakeMongo()
    with _app().test_request_context():
        g.org_id = "cibercom"
        logic.create_usuario(mongo, "ana", None, None, "EMPLOYEE", email="ana@x.com")
        _id = str(mongo.db.usuario.find_one({"user": "ana"})["_id"])
        resp, status = logic.ver_temporal(mongo, _id, {"user": "rh", "role": "RH"})
        assert status == 200 and resp.get_json()["temp_password"] == "Temp-Alta-1"
        resp, _ = logic.get_usuarios(mongo)
    fila = resp.get_json()[0]
    assert fila["tiene_temporal"] is True and "temp_password_cifrada" not in fila


def test_restablecer_guarda_la_nueva_temporal(monkeypatch):
    _aegis(monkeypatch)
    mongo = FakeMongo()
    _id = str(mongo.db.usuario.insert_one({"user": "ana", "email": "ana@x.com", "aegis_user_id": "a-1"}).inserted_id)
    with _app().test_request_context():
        g.org_id = "cibercom"
        resp, status = logic.update_usuario(mongo, _id, password="__reset__", identity={"user": "admin"})
    assert status == 200 and resp.get_json()["temp_password"] == "Temp-Nueva-1"
    assert temporal.leer(mongo.db.usuario.find_one({"user": "ana"})) == "Temp-Nueva-1"


def test_si_aegis_niega_la_temporal_manda_el_enlace_de_recuperacion(monkeypatch):
    _aegis(monkeypatch, reset=(None, ({"detail": "Usa recovery-email"}, 403)))
    enviados = []
    monkeypatch.setattr(logic, "aegis_admin_recovery_email", lambda uid, tenant_id=None: enviados.append(uid))
    mongo = FakeMongo()
    _id = str(mongo.db.usuario.insert_one({"user": "ana", "email": "ana@x.com", "aegis_user_id": "a-1"}).inserted_id)
    with _app().test_request_context():
        g.org_id = "cibercom"
        resp, status = logic.update_usuario(mongo, _id, password="__reset__", identity={"user": "admin"})
    data = resp.get_json()
    assert status == 200 and data["recovery_email_sent"] is True and "temp_password" not in data
    assert enviados == ["a-1"]


def test_sin_temporal_vigente_no_hay_nada_que_ver(monkeypatch):
    _aegis(monkeypatch)
    mongo = FakeMongo()
    _id = str(mongo.db.usuario.insert_one({"user": "ana"}).inserted_id)
    with _app().test_request_context():
        g.org_id = "cibercom"
        _, status = logic.ver_temporal(mongo, _id, {"user": "rh"})
    assert status == 404
