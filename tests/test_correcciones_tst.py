# tests/test_correcciones_tst.py
# Correcciones de las pruebas de TST Retail (oct 2026): sesión deslizante,
# recuperación de contraseña, CLABE/cuenta, teléfonos, SDI automático,
# periodicidad de pago y domicilio configurable.
from bson.objectid import ObjectId
from flask import Flask, g
from flask_jwt_extended import JWTManager, create_access_token, decode_token

from core.bancos_mx import banco_capturado, banco_de_clabe
from core.validadores_mx import validar_clabe, validar_cuenta
from api.datoscontacto.logic import validar_telefonos
from tests.fakes import FakeMongo


def _clabe(prefijo17):
    pesos = (3, 7, 1) * 6
    suma = sum((int(c) * pesos[i]) % 10 for i, c in enumerate(prefijo17))
    return prefijo17 + str((10 - suma % 10) % 10)


def test_clabe_de_ceros_y_cuentas_de_relleno_se_rechazan():
    assert validar_clabe("000000000000000000")  # pasa el dígito de control, pero no hay banco 000
    buena = _clabe("01218000123456789")
    assert validar_clabe(buena) is None and banco_de_clabe(buena) == "BBVA México"
    assert validar_cuenta("12345678901234567890")
    assert validar_cuenta("0000000000")
    assert validar_cuenta("0123456789") and validar_cuenta("1234567890")
    assert validar_cuenta("0482736195") is None


def test_banco_capturado_reconoce_alias():
    assert banco_capturado("bancomer") == "012" and banco_capturado("Banorte") == "072"
    assert banco_capturado("Plata") is None


def test_telefonos_celular_y_fijo_distintos_whatsapp_puede_repetir():
    assert validar_telefonos("55 5658 1111", "5556581111", "")["TelFijo"]
    assert validar_telefonos("", "5556581111", "5556581111") == {}
    assert validar_telefonos("", "123", "")["TelCelular"]


def _app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    from api.login.routes import setup_login_routes
    from api.rh.routes import setup_rh_routes
    from api.nomina.routes import setup_nomina_routes
    setup_login_routes(app, mongo)
    setup_rh_routes(app, mongo)
    setup_nomina_routes(app, mongo)
    return app, mongo


def _h(app, user="ana", role="RH", org="acme"):
    with app.app_context():
        t = create_access_token(identity=user, additional_claims={"user": user, "role": role, "org_id": org, "empleado_id": ""})
    return {"Authorization": f"Bearer {t}"}


def test_refresh_renueva_la_sesion_solo_de_cuentas_activas():
    app, mongo = _app()
    c = app.test_client()
    mongo.db.usuario.insert_one({"user": "ana", "role": "RH", "org_id": "acme"})
    r = c.post("/refresh", headers=_h(app))
    assert r.status_code == 200
    with app.app_context():
        assert decode_token(r.get_json()["access_token"])["org_id"] == "acme"
    mongo.db.usuario.update_one({"user": "ana"}, {"$set": {"activo": False}})
    assert c.post("/refresh", headers=_h(app)).status_code in (401, 403)
    assert c.post("/refresh").status_code == 401


def test_recuperar_contrasena_avisa_al_super_admin_sin_revelar_cuentas():
    app, mongo = _app()
    c = app.test_client()
    mongo.db.usuario.insert_one({"user": "cperez", "email": "cperez@tst.com", "role": "EMPLOYEE", "org_id": "tst"})
    mongo.db.usuario.insert_one({"user": "jefa", "role": "SUPER_ADMIN", "org_id": "tst"})
    ok = c.post("/recuperar-contrasena", json={"identificador": "cperez@tst.com"})
    nadie = c.post("/recuperar-contrasena", json={"identificador": "nadie@x.com"})
    assert ok.status_code == nadie.status_code == 200
    assert ok.get_json()["message"] == nadie.get_json()["message"]
    avisos = list(mongo.db.notificaciones.find({"usuario": "jefa"}))
    assert len(avisos) == 1 and "cperez" in avisos[0]["mensaje"]
    # Repetir no duplica el aviso mientras siga pendiente.
    c.post("/recuperar-contrasena", json={"identificador": "cperez"})
    assert len(list(mongo.db.notificaciones.find({"usuario": "jefa"}))) == 1


def test_sdi_se_calcula_solo_y_el_manual_exige_motivo():
    app, mongo = _app()
    c = app.test_client()
    eid = ObjectId()
    mongo.db.rh.insert_one({"empleado_id": eid, "FechaIngreso": "2026-01-01"})
    r = c.put(f"/rh/{eid}", json={"SalarioDiario": 400, "PeriodicidadPago": "semanal"}, headers=_h(app))
    assert r.status_code == 200, r.get_json()
    rh = mongo.db.rh.find_one({"empleado_id": eid})
    # Primer año: 15 días de aguinaldo + 12 de vacaciones × 25 % → factor 1.0493
    assert rh["SDI_factor"] == round(1 + (15 + 12 * 0.25) / 365, 4)
    assert rh["SalarioDiarioIntegrado"] == round(400 * rh["SDI_factor"], 2)
    assert rh["PeriodicidadPago"] == "semanal"
    r = c.put(f"/rh/{eid}", json={"SDI_manual": True, "SalarioDiarioIntegrado": 450}, headers=_h(app))
    assert r.status_code == 400 and "SDI_motivo" in r.get_json()["campos"]
    r = c.put(f"/rh/{eid}", json={"SDI_manual": True, "SalarioDiarioIntegrado": 450, "SDI_motivo": "Prestaciones superiores"}, headers=_h(app))
    assert r.status_code == 200
    assert c.put(f"/rh/{eid}", json={"PeriodicidadPago": "diaria"}, headers=_h(app)).status_code == 400
    # La calculadora usa la periodicidad del empleado si no se indica.
    calc = c.get(f"/nomina/calcular/{eid}", headers=_h(app)).get_json()
    assert calc["periodo"] == "semanal"


def test_clabe_de_otro_banco_que_el_capturado():
    app, mongo = _app()
    c = app.test_client()
    eid = ObjectId()
    clabe = _clabe("07218000123456789")  # Banorte
    r = c.put(f"/rh/{eid}", json={"Banco": "BBVA", "CLABE": clabe}, headers=_h(app))
    assert r.status_code == 400 and "Banorte" in r.get_json()["campos"]["Banco"]
    r = c.put(f"/rh/{eid}", json={"CLABE": clabe}, headers=_h(app))
    assert r.status_code == 200 and mongo.db.rh.find_one({"empleado_id": eid})["Banco"] == "Banorte"
    assert c.get(f"/bancos?clabe={clabe}", headers=_h(app)).get_json()["banco"] == "Banorte"


def test_domicilio_obligatorios_configurables():
    from api.direccion.logic import validar_direccion
    mongo = FakeMongo()
    app = Flask(__name__)
    with app.app_context():
        errores = validar_direccion(mongo, {"Calle": "Av principal", "NumExterior": "S/N", "CodigoP": "5206"})
        assert {"Colonia", "Municipio", "Ciudad", "CodigoP"} <= set(errores) and "Manzana" not in errores
        mongo.db.organizacion.insert_one({"campos_direccion": {"Colonia": "opcional", "Manzana": "obligatorio"}})
        errores = validar_direccion(mongo, {"Calle": "x", "NumExterior": "1", "Municipio": "m", "Ciudad": "c", "CodigoP": "52060"})
        assert set(errores) == {"Manzana"}
        # Si el domicilio no cambió, no bloquea.
        assert validar_direccion(mongo, {"Calle": "x"}, antes={"Calle": "x"}) == {}


def test_correos_repetidos_en_el_perfil_se_rechazan():
    from api.datoscontacto.logic import validar_correos
    assert validar_correos([{"email": "a@tst.com"}, {"email": "A@tst.com "}])["ListaCorreos"]
    assert validar_correos([{"email": "sin-arroba"}])["ListaCorreos"]
    assert validar_correos([{"email": "a@tst.com"}, {"email": "b@tst.com"}, {"email": ""}]) == {}


def test_no_dos_cuentas_con_el_mismo_correo_o_usuario_en_la_empresa(monkeypatch):
    from api.usuario import logic as U
    monkeypatch.setattr(U, "get_aegis_settings", lambda: {"login_enabled": False, "admin_enabled": False})
    mongo = FakeMongo()
    app = Flask(__name__)
    with app.app_context():
        g.org_id = "tst"
        mongo.db.usuario.insert_one({"user": "cperez", "email": "cperez@tst.com", "org_id": "tst"})
        r, st = U.create_usuario(mongo, "otro", "secreto1", None, email="CPerez@tst.com")
        assert st == 409 and "correo" in r.get_json()["error"]
        r, st = U.create_usuario(mongo, "cperez", "secreto1", None, email="nuevo@tst.com")
        assert st == 409 and "usuario" in r.get_json()["error"]
