# tests/test_recuperacion_codigo.py
#
# "¿Olvidaste tu contraseña?" con código por correo: el código llega solo a
# quien tiene el correo, vence, tiene intentos limitados y no revela si la
# cuenta existe; al confirmar, Aegis restablece y la temporal se usa en el
# acto para fijar la contraseña que eligió la persona.
from flask import Flask

from api.login import recuperacion as rec
from tests.fakes import FakeMongo

NUEVA = "Nueva-Clave-2026"


def _preparar(monkeypatch, cuentas=(("ana", "cibercom"),)):
    enviados = []
    monkeypatch.setattr(rec, "mailer_enabled", lambda: True)
    monkeypatch.setattr(rec, "send_codigo_recuperacion", lambda to, codigo, m: enviados.append((to, codigo)) or True)
    monkeypatch.setattr(rec, "get_aegis_settings", lambda: {"login_enabled": True, "admin_enabled": True})
    llamadas = {}
    monkeypatch.setattr(rec, "aegis_admin_reset_password",
                        lambda uid, tenant_id=None: llamadas.setdefault("reset", (uid, tenant_id)) and ("Temp-XYZ", None))
    monkeypatch.setattr(rec, "aegis_change_password",
                        lambda ident, actual, nueva, tenant_id=None, app_id=None: llamadas.setdefault("cambio", (ident, actual, nueva, tenant_id)) and None)
    monkeypatch.setattr("core.sesiones.revocar_usuario", lambda *a, **k: llamadas.setdefault("revocar", a))
    mongo = FakeMongo()
    for user, org in cuentas:
        mongo.db.raw.usuario.insert_one({"user": user, "email": "ana@x.com", "org_id": org, "aegis_user_id": f"a-{org}"})
    mongo.db.raw.organizacion.insert_one({"org_id": "cibercom", "name": "Cibercom"})
    return mongo, enviados, llamadas


def _json(resp):
    r, status = resp
    return r.get_json(), status


def test_flujo_completo_codigo_verificar_confirmar(monkeypatch):
    mongo, enviados, llamadas = _preparar(monkeypatch)
    with Flask(__name__).test_request_context():
        _, status = _json(rec.solicitar_codigo(mongo, {"email": "ANA@x.com "}, "1.1.1.1"))
        assert status == 200 and enviados[0][0] == "ana@x.com"
        codigo = enviados[0][1]
        assert len(codigo) == 6 and codigo not in str(list(mongo.db.raw.recuperacion_codigos.find()))

        data, status = _json(rec.verificar_codigo(mongo, {"email": "ana@x.com", "codigo": codigo}))
        assert status == 200 and data["empresas"] == [{"org_id": "cibercom", "nombre": "Cibercom"}]

        data, status = _json(rec.confirmar(mongo, {"token": data["token"], "nueva": NUEVA}))
    assert status == 200
    assert llamadas["reset"] == ("a-cibercom", "cibercom")
    assert llamadas["cambio"] == ("ana@x.com", "Temp-XYZ", NUEVA, "cibercom")
    assert "revocar" in llamadas


def test_correo_sin_cuenta_responde_igual_y_no_envia(monkeypatch):
    mongo, enviados, _ = _preparar(monkeypatch)
    with Flask(__name__).test_request_context():
        data, status = _json(rec.solicitar_codigo(mongo, {"email": "nadie@x.com"}, "1.1.1.1"))
        data_ok, _ = _json(rec.solicitar_codigo(mongo, {"email": "ana@x.com"}, "1.1.1.2"))
    assert status == 200 and data["message"] == data_ok["message"]
    assert [e[0] for e in enviados] == ["ana@x.com"]


def test_codigo_incorrecto_agota_intentos(monkeypatch):
    mongo, enviados, _ = _preparar(monkeypatch)
    with Flask(__name__).test_request_context():
        rec.solicitar_codigo(mongo, {"email": "ana@x.com"}, "1.1.1.1")
        malo = "000000" if enviados[0][1] != "000000" else "111111"
        for _ in range(rec.INTENTOS_MAX):
            _, status = _json(rec.verificar_codigo(mongo, {"email": "ana@x.com", "codigo": malo}))
            assert status == 400
        # Ya agotado: ni el código correcto sirve.
        _, status = _json(rec.verificar_codigo(mongo, {"email": "ana@x.com", "codigo": enviados[0][1]}))
    assert status == 400


def test_varias_empresas_se_eligen_despues_de_verificar(monkeypatch):
    mongo, enviados, llamadas = _preparar(monkeypatch, cuentas=(("ana", "cibercom"), ("ana", "otra")))
    with Flask(__name__).test_request_context():
        rec.solicitar_codigo(mongo, {"email": "ana@x.com"}, "1.1.1.1")
        data, _ = _json(rec.verificar_codigo(mongo, {"email": "ana@x.com", "codigo": enviados[0][1]}))
        assert {e["org_id"] for e in data["empresas"]} == {"cibercom", "otra"}
        _, status = _json(rec.confirmar(mongo, {"token": data["token"], "nueva": NUEVA}))
        assert status == 400  # falta elegir empresa
        _, status = _json(rec.confirmar(mongo, {"token": data["token"], "nueva": NUEVA, "org_id": "otra"}))
    assert status == 200 and llamadas["reset"] == ("a-otra", "otra")


def test_contrasena_debil_y_token_de_un_solo_uso(monkeypatch):
    mongo, enviados, _ = _preparar(monkeypatch)
    with Flask(__name__).test_request_context():
        rec.solicitar_codigo(mongo, {"email": "ana@x.com"}, "1.1.1.1")
        data, _ = _json(rec.verificar_codigo(mongo, {"email": "ana@x.com", "codigo": enviados[0][1]}))
        _, status = _json(rec.confirmar(mongo, {"token": data["token"], "nueva": "corta"}))
        assert status == 400
        _, status = _json(rec.confirmar(mongo, {"token": data["token"], "nueva": NUEVA}))
        assert status == 200
        _, status = _json(rec.confirmar(mongo, {"token": data["token"], "nueva": NUEVA}))
    assert status == 400


def test_reenvio_inmediato_no_manda_otro_codigo(monkeypatch):
    mongo, enviados, _ = _preparar(monkeypatch)
    with Flask(__name__).test_request_context():
        rec.solicitar_codigo(mongo, {"email": "ana@x.com"}, "1.1.1.1")
        rec.solicitar_codigo(mongo, {"email": "ana@x.com"}, "1.1.1.1")
    assert len(enviados) == 1
