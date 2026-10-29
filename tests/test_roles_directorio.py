# tests/test_roles_directorio_recuperacion.py
#
# Observaciones oct 2026:
#  - Gestión de roles: cualquier rol (salvo SUPER_ADMIN) se puede eliminar y
#    volver a crear de cero; los permisos editados de un rol de sistema se
#    guardan en el servidor (antes solo en el localStorage del admin).
#  - Directorio: un empleado general ve de sus compañeros solo lo que su rol
#    permite (contacto laboral, estado, puesto…), nunca lo personal.
from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.perfil.routes import setup_perfil_routes
from api.roles.routes import setup_roles_routes
from core.permissions import get_permisos_for_role, rol_existe
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


def test_organigrama_por_jefe_inmediato_sin_bajas():
    mongo = FakeMongo()
    jefe = _empleado(mongo, "Jefa")["_id"]
    sub = _empleado(mongo, "Sub")["_id"]
    baja = _empleado(mongo, "Ido", estado="baja")["_id"]
    mongo.db.rh.insert_one({"empleado_id": sub, "JefeInmediato_id": str(jefe), "Puesto": "Dev"})
    mongo.db.rh.insert_one({"empleado_id": jefe, "JefeInmediato_id": str(baja)})
    app = _app(mongo)
    r = app.test_client().get("/organigrama", headers={"Authorization": f"Bearer {_token(app, 'EMPLOYEE')}"})
    nodos = {n["Nombre"]: n for n in r.get_json()}
    assert set(nodos) == {"Jefa", "Sub"}
    assert nodos["Sub"]["JefeInmediato_id"] == str(jefe)
    assert nodos["Jefa"]["JefeInmediato_id"] == ""  # su jefe está de baja
