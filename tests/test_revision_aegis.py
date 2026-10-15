# Correcciones de la revisión del 15 oct 2026. Pasan por el middleware real
# y por FakeMongo. No importan app.py ni abren la base del proyecto.
import os
from datetime import datetime, timedelta, timezone

from flask import Flask, g, jsonify
from flask_jwt_extended import JWTManager, get_jwt, verify_jwt_in_request

from api.acceso.solicitudes import crear_solicitud
from api.auth_decorators import require_roles
from api.dispositivos.routes import setup_dispositivos_routes
from api.login.logic import login
from api.login.routes import setup_login_routes
from api.login.sesion import _renovar_aegis, renovar
from core.controles_request import aplicar
from core.designacion_admin import designar_si_corresponde
from core.perfiles_aegis import clasificar_perfiles
from core.sesiones import crear, obtener
from core.vinculo_identidad import buscar_usuario_por_par
from tests.fakes import FakeMongo

TENANT = "11111111-1111-1111-1111-111111111111"
USUARIO = "22222222-2222-2222-2222-222222222222"


def _ajustes():
    return {
        "login_enabled": True, "tenant_id": "cibercom", "app_id": "empleados",
        "legacy_fallback": False, "admin_enabled": False,
    }


def _perfil(**extra):
    base = {
        "id": USUARIO, "email": "ana@acme.test", "tenant_id": TENANT,
        "app_key": "empleados", "is_active": True, "must_change_password": False,
        "roles": ["user"], "scopes": [],
    }
    base.update(extra)
    return base


def _acceso(roles):
    return {
        "allowed": True, "tenant_id": TENANT, "app_key": "empleados",
        "mode": "product", "roles": roles, "scopes": [],
    }


def _app(mongo):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    app.config["JWT_TOKEN_LOCATION"] = ["headers", "cookies"]
    app.config["JWT_COOKIE_CSRF_PROTECT"] = False
    JWTManager(app)
    setup_login_routes(app, mongo)
    setup_dispositivos_routes(app, mongo)

    @app.before_request
    def _contexto():
        g.org_id = None
        g.contexto_privado = False
        g.sesion_servidor = None
        claims = None
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
        except Exception:
            claims = None
        return aplicar(mongo, claims)

    @app.route("/nota", methods=["POST"])
    def nota():
        return jsonify({"ok": True, "org": g.org_id}), 200

    @app.route("/zona-admin", methods=["GET"])
    @require_roles("SUPER_ADMIN")
    def zona_admin():
        return jsonify({"ok": True}), 200

    @app.route("/privado-abierto", methods=["GET"])
    def privado_abierto():
        return jsonify({"ok": True}), 200

    return app


def _parchear(monkeypatch, acceso):
    monkeypatch.setattr("api.login.logic.get_aegis_settings", lambda: _ajustes())
    monkeypatch.setattr("api.login.sesion.get_aegis_settings", lambda: _ajustes())
    monkeypatch.setattr("core.aegis_config.get_aegis_settings", lambda: _ajustes())
    monkeypatch.setattr("api.login.logic.aegis_resolve_tenant", lambda identifier, app: ({
        "tenant_key": "acme", "tenant_name": "Acme", "app_key": app,
    }, None))
    monkeypatch.setattr("api.login.logic.aegis_password_login", lambda *a, **k: ({
        "access_token": "acceso", "refresh_token": "r" * 24,
        "must_change_password": False,
    }, None))
    monkeypatch.setattr("api.login.logic.aegis_get_me", lambda *a, **k: (_perfil(), None))
    monkeypatch.setattr("api.login.logic.aegis_get_access", acceso)
    monkeypatch.setattr("core.aegis_client.aegis_get_access", acceso)


def test_user_es_perfil_ordinario():
    assert clasificar_perfiles(["user"]) == "ordinario"


def test_login_con_access_403_abre_sesion_restringida(monkeypatch):
    def acceso(*_a, **_k):
        return None, ({"detail": "Password change required"}, 403)

    _parchear(monkeypatch, acceso)
    mongo = FakeMongo()
    app = _app(mongo)
    cliente = app.test_client()
    respuesta = cliente.post("/login", json={"user": "ana@acme.test", "password": "Temporal123!"})
    assert respuesta.status_code == 200, respuesta.get_json()
    cuerpo = respuesta.get_json()
    assert cuerpo["must_change_password"] is True
    assert cuerpo.get("csrf_token")
    assert "access_token" not in cuerpo
    assert "empleados_sid" in respuesta.headers.get("Set-Cookie", "")
    assert cliente.post("/nota", json={}).status_code == 403


def test_cambio_de_la_sesion_restringida_pide_relogin(monkeypatch):
    def acceso(*_a, **_k):
        return None, ({"detail": "Password change required"}, 403)

    _parchear(monkeypatch, acceso)
    monkeypatch.setattr("api.login.logic.aegis_change_password", lambda *a, **k: None)
    mongo = FakeMongo()
    cliente = _app(mongo).test_client()
    entrada = cliente.post("/login", json={"user": "ana@acme.test", "password": "Temporal123!"})
    token = entrada.get_json()["csrf_token"]
    cambio = cliente.post("/change-password", json={
        "current_password": "Temporal123!", "new_password": "NuevaClave123!",
    }, headers={"X-CSRF-Token": token})
    assert cambio.status_code == 200
    assert cambio.get_json()["reautenticar"] is True


def test_csrf_en_cuerpo_y_origen_ajeno(monkeypatch):
    def acceso(*_a, **_k):
        return _acceso(["user"]), None

    _parchear(monkeypatch, acceso)
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "ana@acme.test", "email": "ana@acme.test", "org_id": "acme",
        "role": "EMPLOYEE", "activo": True,
        "aegis_user_id": USUARIO, "aegis_tenant_id": TENANT,
    })
    cliente = _app(mongo).test_client()
    entrada = cliente.post("/login", json={"user": "ana@acme.test", "password": "ClaveCorrecta12!"})
    assert entrada.status_code == 200, entrada.get_json()
    assert cliente.post("/nota", json={"texto": "hola"}).status_code == 403
    ok = cliente.post("/nota", json={"texto": "hola"}, headers={"X-CSRF-Token": entrada.get_json()["csrf_token"]})
    assert ok.status_code == 200

    previo = os.environ.get("CORS_ALLOWED_ORIGINS")
    os.environ["CORS_ALLOWED_ORIGINS"] = "https://cibercomrh.com"
    try:
        ajeno = cliente.post(
            "/login",
            json={"user": "ana@acme.test", "password": "x"},
            headers={"Origin": "https://evil.example"},
        )
        assert ajeno.status_code == 403
    finally:
        if previo is None:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        else:
            os.environ["CORS_ALLOWED_ORIGINS"] = previo


def test_ruta_privada_sin_sesion_responde_401(monkeypatch):
    monkeypatch.setattr("core.aegis_config.get_aegis_settings", lambda: _ajustes())
    cliente = _app(FakeMongo()).test_client()
    assert cliente.get("/privado-abierto").status_code == 401
    assert cliente.get("/org/acme/config").status_code == 404


def test_dispositivo_deshabilitado_con_aegis(monkeypatch):
    monkeypatch.setattr("core.aegis_config.get_aegis_settings", lambda: _ajustes())
    cliente = _app(FakeMongo()).test_client()
    respuesta = cliente.post("/login/dispositivo", json={"dispositivo_id": "x", "llave": "y"})
    assert respuesta.status_code == 403
    assert "deshabilitado" in respuesta.get_json()["error"]


def test_admin_pasa_a_user_y_pierde_gestion(monkeypatch):
    roles = {"actual": ["admin"]}

    def acceso(*_a, **_k):
        return _acceso(roles["actual"]), None

    _parchear(monkeypatch, acceso)
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "ana@acme.test", "email": "ana@acme.test", "org_id": "acme",
        "role": "SUPER_ADMIN", "plataforma": False, "activo": True,
        "aegis_user_id": USUARIO, "aegis_tenant_id": TENANT,
    })
    cliente = _app(mongo).test_client()
    entrada = cliente.post("/login", json={"user": "ana@acme.test", "password": "ClaveCorrecta12!"})
    assert entrada.status_code == 200
    assert entrada.get_json()["role"] == "SUPER_ADMIN"
    assert mongo.db.usuario.find_one({})["role"] == "SUPER_ADMIN"
    roles["actual"] = ["user"]
    previo = os.environ.get("AEGIS_ACCESS_CACHE_SECONDS")
    os.environ["AEGIS_ACCESS_CACHE_SECONDS"] = "0"
    try:
        zona = cliente.get("/zona-admin")
    finally:
        if previo is None:
            os.environ.pop("AEGIS_ACCESS_CACHE_SECONDS", None)
        else:
            os.environ["AEGIS_ACCESS_CACHE_SECONDS"] = previo
    assert zona.status_code == 403
    assert mongo.db.usuario.find_one({})["role"] == "SUPER_ADMIN"
    assert mongo.db.sesiones.find_one({})["rol_efectivo"] == "EMPLOYEE"


def test_recuperar_sin_liga_no_dice_que_envio_correo(monkeypatch):
    llamadas = []
    monkeypatch.setattr("api.login.sesion.get_aegis_settings", lambda: _ajustes())
    monkeypatch.setattr(
        "core.aegis_client.aegis_password_reset_request",
        lambda *a, **k: llamadas.append(a),
    )
    cliente = _app(FakeMongo()).test_client()
    una = cliente.post("/recuperar-contrasena", json={"identificador": "ana@acme.test"})
    otra = cliente.post("/recuperar-contrasena", json={"identificador": "nadie@acme.test"})
    assert una.status_code == otra.status_code == 400
    assert una.get_json() == otra.get_json()
    assert "correo" not in una.get_json()["error"].lower() or "página" in una.get_json()["error"]
    assert llamadas == []


def test_misma_clave_con_otro_payload_no_repite_ni_enumera(monkeypatch):
    import api.acceso.solicitudes as solicitudes
    from core.public_rate_limit import RegistrationRateLimiter
    solicitudes._limite = RegistrationRateLimiter(max_attempts=20, window_seconds=3600)
    mongo = FakeMongo()
    app = Flask(__name__)
    with app.test_request_context():
        ok, status = crear_solicitud(mongo, {
            "empresa": "Acme", "contacto": "Ana Ruiz", "correo": "ana@acme.test",
        }, "10.0.0.8", "clave-1")
        conflicto, status2 = crear_solicitud(mongo, {
            "empresa": "Otra", "contacto": "Ana Ruiz", "correo": "ana@acme.test",
        }, "10.0.0.8", "clave-1")
    assert status == 202 and status2 == 409
    assert conflicto.get_json()["error"] == "La solicitud no coincide con un envío ya recibido."
    assert "ana@acme.test" not in conflicto.get_json()["error"]
    assert mongo.db.solicitudes_acceso.count_documents({}) == 1
    assert ok.get_json()["message"]


def test_reloj_controlado_alarga_y_vence():
    momento = {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)}

    def reloj():
        return momento["t"]

    import core.sesiones as sesiones
    original = sesiones.ahora
    sesiones.ahora = reloj
    try:
        mongo = FakeMongo()
        sesion = crear(
            mongo, user="ana", org_id="acme",
            claims={"user": "ana", "role": "EMPLOYEE", "org_id": "acme"},
            minutos=15,
        )
        momento["t"] += timedelta(minutes=10)
        assert obtener(mongo, sesion["sid"])
        from core.sesiones import prorrogar
        assert prorrogar(mongo, sesion["sid"], 15)
        momento["t"] += timedelta(minutes=10)
        assert obtener(mongo, sesion["sid"])
        momento["t"] += timedelta(minutes=6)
        assert obtener(mongo, sesion["sid"]) is None
    finally:
        sesiones.ahora = original


def test_refresh_5xx_no_revoca_y_no_reutiliza_el_par_viejo(monkeypatch):
    vistos = []

    def refrescar(token, tenant_id=None, app_id=None):
        vistos.append(token)
        if len(vistos) == 1:
            return {"access_token": "acceso-2", "refresh_token": "refresh-2"}, None
        return None, ({"error": "caido"}, 503)

    def acceso(*_a, **_k):
        return None, ({"error": "caido"}, 503)

    monkeypatch.setattr("api.login.sesion.aegis_refresh", refrescar)
    monkeypatch.setattr("api.login.sesion.aegis_get_access", acceso)
    monkeypatch.setattr("api.login.sesion.get_aegis_settings", lambda: _ajustes())
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({"user": "ana", "org_id": "acme", "role": "EMPLOYEE", "activo": True})
    sesion = crear(
        mongo, user="ana", org_id="acme",
        claims={"user": "ana", "role": "EMPLOYEE", "org_id": "acme"},
        aegis={"access_token": "acceso-1", "refresh_token": "refresh-1", "user_id": USUARIO, "tenant_id": TENANT},
        minutos=15,
    )
    app = Flask(__name__)
    with app.test_request_context():
        resp, status = _renovar_aegis(mongo, {"user": "ana", "org_id": "acme"}, lambda *a, **k: (jsonify({}), 200), sesion)
    assert status == 503
    guardada = mongo.db.sesiones.find_one({"sid": sesion["sid"]})
    assert guardada["revocada"] is not True
    assert guardada["refresh_token"] == "refresh-2"
    vigente = obtener(mongo, sesion["sid"])
    with app.test_request_context():
        _resp2, status2 = _renovar_aegis(
            mongo, {"user": "ana", "org_id": "acme"}, lambda *a, **k: (jsonify({}), 200), vigente,
        )
    assert status2 == 503
    assert vistos[1] == "refresh-2"


def test_perdedor_del_lease_no_revoca(monkeypatch):
    monkeypatch.setattr(
        "api.login.sesion.aegis_refresh",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe llamar")),
    )
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({"user": "ana", "org_id": "acme", "role": "EMPLOYEE", "activo": True})
    sesion = crear(
        mongo, user="ana", org_id="acme",
        claims={"user": "ana", "role": "EMPLOYEE", "org_id": "acme"},
        aegis={"access_token": "a", "refresh_token": "r", "user_id": USUARIO, "tenant_id": TENANT},
        minutos=15,
    )
    mongo.db.sesiones.update_one(
        {"sid": sesion["sid"]},
        {"$set": {"lease_hasta": "2099-01-01T00:00:00+00:00", "lease_dueno": "otro"}},
    )
    app = Flask(__name__)
    with app.test_request_context():
        _resp, status = _renovar_aegis(
            mongo, {"user": "ana", "org_id": "acme"}, lambda *a, **k: (jsonify({}), 200), obtener(mongo, sesion["sid"]),
        )
    assert status == 503
    assert mongo.db.sesiones.find_one({"sid": sesion["sid"]})["revocada"] is not True


def test_buscar_par_no_escribe_y_un_duplicado_es_conflicto():
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "ana", "org_id": "acme", "role": "EMPLOYEE", "aegis_user_id": USUARIO,
    })
    encontrado = buscar_usuario_por_par(mongo, USUARIO, TENANT, "acme")
    assert encontrado["user"] == "ana"
    assert mongo.db.usuario.find_one({}).get("aegis_tenant_id") in (None, "")
    mongo.db.usuario.insert_one({
        "user": "ana2", "org_id": "otra", "role": "EMPLOYEE",
        "aegis_user_id": USUARIO, "aegis_tenant_id": TENANT,
    })
    assert buscar_usuario_por_par(mongo, USUARIO, TENANT, "acme") is None


def test_designacion_parcial_se_completa_una_sola_vez():
    mongo = FakeMongo()
    mongo.db.designacion_admin.insert_one({
        "org_id": "acme", "aegis_user_id": USUARIO, "aegis_tenant_id": TENANT,
    })
    perfil = _perfil(roles=["admin"])
    primero = designar_si_corresponde(mongo, "acme", perfil, ["admin"])
    segundo = designar_si_corresponde(mongo, "acme", perfil, ["admin"])
    assert primero and primero["role"] == "SUPER_ADMIN" and primero["plataforma"] is False
    assert segundo["user"] == primero["user"]
    assert mongo.db.usuario.count_documents({"role": "SUPER_ADMIN"}) == 1


def test_sesion_vencida_no_renueva(monkeypatch):
    momento = {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    import core.sesiones as sesiones
    original = sesiones.ahora
    sesiones.ahora = lambda: momento["t"]
    monkeypatch.setattr("api.login.sesion.get_aegis_settings", lambda: _ajustes())
    try:
        mongo = FakeMongo()
        mongo.db.usuario.insert_one({"user": "ana", "org_id": "acme", "role": "EMPLOYEE", "activo": True})
        sesion = crear(
            mongo, user="ana", org_id="acme",
            claims={"user": "ana", "role": "EMPLOYEE", "org_id": "acme"},
            aegis={"refresh_token": "r", "access_token": "a"},
            minutos=15,
        )
        momento["t"] += timedelta(minutes=16)
        app = Flask(__name__)
        with app.test_request_context():
            resp, status = renovar(
                mongo, {"user": "ana", "org_id": "acme", "sid": sesion["sid"]},
                lambda *a, **k: (jsonify({}), 200),
            )
        assert status == 401
    finally:
        sesiones.ahora = original


def test_login_directo_tambien_trata_el_403_de_cambio(monkeypatch):
    def acceso(*_a, **_k):
        return None, ({"detail": "Password change required"}, 403)

    _parchear(monkeypatch, acceso)
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    with app.test_request_context():
        resp, status = login(FakeMongo(), "ana@acme.test", "Temporal123!")
    assert status == 200
    assert resp.get_json()["must_change_password"] is True
    assert "access_token" not in resp.get_json()
