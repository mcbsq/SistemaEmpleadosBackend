# tests/test_roles_directorio_recuperacion.py
#
# Observaciones oct 2026:
#  - Gestión de roles: cualquier rol (salvo SUPER_ADMIN) se puede eliminar y
#    volver a crear de cero; los permisos editados de un rol de sistema se
#    guardan en el servidor (antes solo en el localStorage del admin).
#  - Directorio: un empleado general ve de sus compañeros solo lo que su rol
#    permite (contacto laboral, estado, puesto…), nunca lo personal.
#  - "Olvidé mi contraseña": Aegis genera la temporal, se envía por correo y
#    el token de esa sesión solo sirve para definir la nueva.
from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.login import sesion
from api.login.logic import _issue_token_response, _tras_cambio
from api.perfil.routes import setup_perfil_routes
from api.roles.routes import setup_roles_routes
from core.permissions import PERMISOS_DEFAULT, get_permisos_for_role, rol_existe
from core.visibilidad_perfil import tarjeta_directorio
from tests.fakes import FakeMongo


def _app(mongo):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "x" * 40
    JWTManager(app)
    setup_roles_routes(app, mongo)
    setup_perfil_routes(app, mongo)
    return app


def _token(app, role="SUPER_ADMIN", empleado_id=""):
    with app.app_context():
        return create_access_token(identity="yo", additional_claims={
            "user": "yo", "role": role, "empleado_id": empleado_id, "org_id": "cibercom"})


# ─── Roles ───────────────────────────────────────────────────────────────────
def test_permisos_de_sistema_editados_y_rol_eliminado():
    mongo = FakeMongo()
    assert "dir_contacto" in get_permisos_for_role(mongo, "EMPLOYEE")
    mongo.db.roles_custom.insert_one({"tipo": "custom", "roles": [],
                                      "permisos_sistema": {"EMPLOYEE": ["ver_organigrama"]},
                                      "sistema_eliminados": ["MEDICO"]})
    assert get_permisos_for_role(mongo, "EMPLOYEE") == ["ver_organigrama"]
    assert get_permisos_for_role(mongo, "MEDICO") == []
    assert not rol_existe(mongo, "MEDICO")
    assert rol_existe(mongo, "SUPER_ADMIN")


def test_eliminar_rol_de_sistema_y_recrearlo_de_cero():
    mongo = FakeMongo()
    app = _app(mongo)
    h = {"Authorization": f"Bearer {_token(app)}"}
    c = app.test_client()

    assert c.delete("/roles/SUPER_ADMIN", headers=h).status_code == 400
    # Con nombre de sistema vigente no se puede crear uno personalizado.
    assert c.post("/roles/custom", json=[{"nombre": "MEDICO", "permisos": []}], headers=h).status_code == 409

    assert c.delete("/roles/MEDICO", headers=h).status_code == 200
    assert c.get("/roles/config", headers=h).get_json()["sistema_eliminados"] == ["MEDICO"]

    # Recreado de cero: ahora manda el rol personalizado.
    r = c.post("/roles/custom", json=[{"nombre": "medico", "permisos": ["ver_expediente"]}], headers=h)
    assert r.status_code == 200
    assert get_permisos_for_role(mongo, "MEDICO") == ["ver_expediente"]
    assert rol_existe(mongo, "MEDICO")


def test_no_se_elimina_un_rol_asignado():
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({"user": "ana", "role": "JEFE_AREA"})
    app = _app(mongo)
    r = app.test_client().delete("/roles/JEFE_AREA", headers={"Authorization": f"Bearer {_token(app)}"})
    assert r.status_code == 409


def test_solo_super_admin_edita_permisos_de_sistema():
    mongo = FakeMongo()
    app = _app(mongo)
    c = app.test_client()
    body = {"permisos": ["ver_organigrama", "dir_estado"]}
    assert c.put("/roles/sistema/EMPLOYEE/permisos", json=body,
                 headers={"Authorization": f"Bearer {_token(app, 'ADMIN')}"}).status_code == 403
    assert c.put("/roles/sistema/EMPLOYEE/permisos", json=body,
                 headers={"Authorization": f"Bearer {_token(app)}"}).status_code == 200
    assert get_permisos_for_role(mongo, "EMPLOYEE") == ["dir_estado", "ver_organigrama"]


# ─── Directorio ──────────────────────────────────────────────────────────────
def _empleado(mongo, nombre="Luis", **extra):
    eid = mongo.db.empleados.insert_one({"Nombre": nombre, "ApelPaterno": "Pérez",
                                         "FecNacimiento": "1990-03-14", **extra}).inserted_id
    return mongo.db.empleados.find_one({"_id": eid})


def test_companero_ve_contacto_laboral_y_estado_pero_no_lo_personal():
    mongo = FakeMongo()
    emp = _empleado(mongo)
    rh = {"Puesto": "Dev", "Extension": "1234", "TelefonoOficina": "5512345678"}
    contacto = {"TelCelular": "5599999999"}
    yo = {"role": "EMPLOYEE", "empleado_id": str(ObjectId())}
    t = tarjeta_directorio(mongo, yo, emp, rh, {"email": "luis@empresa.com"}, contacto)
    assert t["Extension"] == "1234" and t["CorreoLaboral"] == "luis@empresa.com"
    assert t["estado"] == "activo" and t["Cumpleanos"] == "03-14"
    assert "TelCelular" not in t

    # Sin el permiso de contacto en su rol, ya no lo ve.
    mongo.db.roles_custom.insert_one({"tipo": "custom", "permisos_sistema": {"EMPLOYEE": ["dir_estado"]}})
    t = tarjeta_directorio(mongo, yo, emp, rh, {"email": "luis@empresa.com"}, contacto)
    assert "Extension" not in t and "Puesto" not in t and t["estado"] == "activo"


def test_estado_vacaciones(monkeypatch):
    from datetime import date
    mongo = FakeMongo()
    emp = _empleado(mongo)
    hoy = date.today().isoformat()
    mongo.db.vacaciones_solicitudes.insert_one({"empleado_id": emp["_id"], "estado": "aprobada",
                                                "fecha_inicio": hoy, "fecha_fin": "2999-01-01"})
    t = tarjeta_directorio(mongo, {"role": "EMPLOYEE"}, emp)
    assert t["estado"] == "vacaciones" and t["hasta"] == "2999-01-01"


def test_cadena_mando_tres_niveles_arriba():
    mongo = FakeMongo()
    ids = [_empleado(mongo, f"N{i}")["_id"] for i in range(5)]  # N0 jefe máximo … N4
    for i in range(1, 5):
        mongo.db.rh.insert_one({"empleado_id": ids[i], "JefeInmediato_id": str(ids[i - 1]), "Puesto": f"P{i}"})
    mongo.db.rh.insert_one({"empleado_id": ids[0], "Puesto": "Director"})
    app = _app(mongo)
    r = app.test_client().get(f"/perfil/{ids[4]}/cadena-mando",
                              headers={"Authorization": f"Bearer {_token(app, 'EMPLOYEE')}"})
    d = r.get_json()
    assert [n["Nombre"] for n in d["superiores"]] == ["N1", "N2", "N3"]
    assert d["actual"]["Nombre"] == "N4" and d["hay_mas_arriba"] is True
    r = app.test_client().get(f"/perfil/{ids[3]}/cadena-mando",
                              headers={"Authorization": f"Bearer {_token(app, 'EMPLOYEE')}"})
    assert [n["Nombre"] for n in r.get_json()["directos"]] == ["N4"]


# ─── Olvidé mi contraseña ────────────────────────────────────────────────────
def _aegis(monkeypatch, temp="Temp-123"):
    monkeypatch.setattr("core.aegis_config.get_aegis_settings",
                        lambda: {"admin_enabled": True, "login_enabled": True})
    monkeypatch.setattr("core.aegis_client.aegis_admin_reset_password", lambda uid, tenant_id=None: (temp, None))


def test_recuperacion_resetea_en_aegis_y_envia_correo(monkeypatch):
    enviados = []
    _aegis(monkeypatch)
    monkeypatch.setattr("core.mailer.mailer_enabled", lambda: True)
    monkeypatch.setattr("core.mailer.send_temp_password_email",
                        lambda to, user, temp, login_url=None, restablecida=False: enviados.append((to, temp, restablecida)) or True)
    mongo = FakeMongo()
    mongo.db.raw.usuario.insert_one({"user": "ana", "email": "ana@x.com", "org_id": "cibercom", "aegis_user_id": "a1"})
    with Flask(__name__).test_request_context():
        _, status = sesion.solicitar_recuperacion(mongo, {"identificador": "ana@x.com"}, "1.1.1.1")
        assert status == 200
        # Segunda solicitud inmediata: no vuelve a cambiarla.
        sesion.solicitar_recuperacion(mongo, {"identificador": "ana@x.com"}, "1.1.1.2")
    assert enviados == [("ana@x.com", "Temp-123", True)]
    assert mongo.db.raw.usuario.find_one({"user": "ana"})["debe_cambiar_password"] is True


def test_sin_correo_no_se_toca_la_contrasena(monkeypatch):
    llamadas = []
    monkeypatch.setattr("core.aegis_client.aegis_admin_reset_password", lambda *a, **k: llamadas.append(1) or ("t", None))
    monkeypatch.setattr("core.mailer.mailer_enabled", lambda: False)
    mongo = FakeMongo()
    mongo.db.raw.usuario.insert_one({"user": "ana", "email": "ana@x.com", "org_id": "cibercom", "aegis_user_id": "a1"})
    with Flask(__name__).test_request_context():
        sesion.solicitar_recuperacion(mongo, {"identificador": "ana"}, "1.1.1.3")
    assert llamadas == []
    assert mongo.db.raw.recuperaciones.find_one({"user": "ana"})["atendida"] is False


def test_token_temporal_y_cambio_emite_sesion_normal(monkeypatch):
    monkeypatch.setattr("api.login.logic.verificar_fechas_especiales", lambda m: None)
    monkeypatch.setattr("api.login.logic.get_session_minutes", lambda m, o: 15)
    mongo = FakeMongo()
    mongo.db.raw.usuario.insert_one({"user": "ana", "role": "EMPLOYEE", "org_id": "cibercom", "debe_cambiar_password": True})
    usuario = mongo.db.raw.usuario.find_one({"user": "ana"})
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "x" * 40
    JWTManager(app)
    with app.test_request_context():
        resp, _ = _issue_token_response(mongo, usuario, "ana")
        assert resp.get_json()["must_change_password"] is True
        resp, status = _tras_cambio(mongo, usuario, {"user": "ana", "org_id": "cibercom", "pwd_temp": True})
        data = resp.get_json()
    assert status == 200 and data["access_token"] and data["must_change_password"] is False
    assert "debe_cambiar_password" not in mongo.db.raw.usuario.find_one({"user": "ana"})
    assert set(PERMISOS_DEFAULT["EMPLOYEE"]) <= set(data["permisos"])
