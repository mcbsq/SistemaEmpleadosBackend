# Fases de integración con Aegis. No llama a la red ni a una base real.
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, g
from flask_jwt_extended import JWTManager, create_access_token

from api.acceso.solicitudes import crear_solicitud, listar
from api.login.logic import login
from core.aegis_client import alcance_de_clave
from core.contrasena import contrasena_aceptable
from core.designacion_admin import designar_si_corresponde
from core.perfiles_aegis import clasificar_perfiles, misma_empresa_y_app
from core.sesiones import acceso_en_cache, crear, rotar
from core.tenant_db import BaseDatosMultiTenant, ContextoEmpresaFaltante
from core.vinculo_identidad import buscar_usuario_por_par, plan_vinculos
from tests.fakes import FakeMongo

TENANT = "11111111-1111-1111-1111-111111111111"
USUARIO = "22222222-2222-2222-2222-222222222222"
OTRO = "33333333-3333-3333-3333-333333333333"


def _ajustes():
    return {
        "login_enabled": True, "tenant_id": "cibercom", "app_id": "empleados",
        "legacy_fallback": False, "admin_enabled": False,
    }


def _perfil(uid=USUARIO, roles=None):
    return {
        "id": uid, "email": "ana@acme.test", "tenant_id": TENANT,
        "app_key": "empleados", "is_active": True, "must_change_password": False,
        "roles": roles or ["empleado"], "scopes": [],
    }


def _acceso(roles=None, allowed=True, tenant=TENANT):
    return {
        "allowed": allowed, "tenant_id": tenant, "app_key": "empleados",
        "mode": "product", "roles": roles or ["empleado"], "scopes": [],
    }


def _preparar(monkeypatch, *, roles, me=None, acceso=None, resolve=None, login_error=None):
    llamadas = {"login": [], "resolve": [], "legacy": []}
    monkeypatch.setattr("api.login.logic.get_aegis_settings", lambda: _ajustes())
    monkeypatch.setattr("api.login.logic.check_password_hash", lambda *_a, **_k: llamadas["legacy"].append(1) or False)

    def resolver(identifier, app):
        llamadas["resolve"].append(app)
        if resolve:
            return resolve
        return ({
            "tenant_key": "acme", "tenant_name": "Acme", "app_key": app, "identifier_kind": "full_email",
        }, None)

    def entrar(identifier, password, tenant_id=None, app_id=None):
        llamadas["login"].append(app_id)
        if login_error:
            return None, login_error
        return ({
            "access_token": "acceso", "refresh_token": "r" * 24,
            "must_change_password": False, "expires_in": 60, "token_type": "bearer",
        }, None)

    monkeypatch.setattr("api.login.logic.aegis_resolve_tenant", resolver)
    monkeypatch.setattr("api.login.logic.aegis_password_login", entrar)
    monkeypatch.setattr("api.login.logic.aegis_get_me", lambda *_a, **_k: (me or _perfil(roles=roles), None))
    monkeypatch.setattr("api.login.logic.aegis_get_access", lambda *_a, **_k: (acceso or _acceso(roles), None))
    return llamadas


def _entrar(mongo, **kwargs):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    with app.test_request_context():
        return login(mongo, "ana@acme.test", "clave-correcta-12", **kwargs)


def test_resolver_404_429_503_no_cambia_de_app_ni_usa_hash(monkeypatch):
    for status in (404, 429, 503):
        mongo = FakeMongo()
        llamadas = _preparar(monkeypatch, roles=["empleado"], resolve=(None, ({"error": "x"}, status)))
        _resp, codigo = _entrar(mongo)
        assert codigo == {404: 401, 429: 429, 503: 503}[status]
        assert llamadas["login"] == []
        assert llamadas["legacy"] == []
        assert llamadas["resolve"] == ["empleados"]


def test_resolver_409_pide_la_liga(monkeypatch):
    _preparar(monkeypatch, roles=["empleado"], resolve=(None, ({"error": "ambiguo"}, 409)))
    _resp, codigo = _entrar(FakeMongo())
    assert codigo == 409


def test_rechazo_de_credenciales_no_usa_mongo(monkeypatch):
    llamadas = _preparar(monkeypatch, roles=["empleado"], login_error=({"error": "no"}, 401))
    _resp, codigo = _entrar(FakeMongo())
    assert codigo == 401
    assert llamadas["legacy"] == []
    assert llamadas["login"] == ["empleados"]


def test_perfil_ordinario_no_se_vuelve_admin_aunque_la_base_este_vacia(monkeypatch):
    _preparar(monkeypatch, roles=["empleado"])
    mongo = FakeMongo()
    _resp, codigo = _entrar(mongo)
    assert codigo == 403
    assert mongo.db.usuario.count_documents({}) == 0


def test_perfil_privilegiado_desconocido_se_niega(monkeypatch):
    assert clasificar_perfiles(["super_admin"]) == "denegado"
    _preparar(monkeypatch, roles=["super_admin"])
    mongo = FakeMongo()
    _resp, codigo = _entrar(mongo)
    assert codigo == 403
    assert mongo.db.usuario.count_documents({}) == 0


def test_admin_designado_es_idempotente_y_no_es_plataforma(monkeypatch):
    _preparar(monkeypatch, roles=["admin"])
    mongo = FakeMongo()
    resp, codigo = _entrar(mongo)
    assert codigo == 200
    cuerpo = resp.get_json()
    assert cuerpo["role"] == "SUPER_ADMIN"
    assert cuerpo["plataforma"] is False
    guardado = mongo.db.usuario.find_one({})
    assert guardado["plataforma"] is False
    assert guardado["aegis_user_id"] == USUARIO
    assert guardado["aegis_tenant_id"] == TENANT
    resp2, codigo2 = _entrar(mongo)
    assert codigo2 == 200
    assert mongo.db.usuario.count_documents({}) == 1
    assert resp2.get_json()["role"] == "SUPER_ADMIN"


def test_designacion_concurrente_deja_un_solo_admin():
    mongo = FakeMongo()
    resultados = []

    def intentar(uid):
        perfil = _perfil(uid=uid)
        resultados.append(designar_si_corresponde(mongo, "acme", perfil, ["admin"]))

    hilos = [threading.Thread(target=intentar, args=(uid,)) for uid in (USUARIO, OTRO)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    assert mongo.db.usuario.count_documents({"role": "SUPER_ADMIN"}) == 1
    assert all((r is None) or (r.get("plataforma") is False) for r in resultados)


def test_alias_y_correo_repetido_no_enlazan_otra_identidad():
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "ana", "email": "ana@otra.test", "org_id": "otra",
        "aegis_user_id": OTRO, "aegis_tenant_id": "99999999-9999-9999-9999-999999999999",
    })
    assert buscar_usuario_por_par(mongo, USUARIO, TENANT, "acme") is None
    plan = plan_vinculos([
        {"_id": "1", "user": "ana", "email": "ana@acme.test", "org_id": "acme", "role": "EMPLOYEE", "activo": True},
        {"_id": "2", "user": "ana", "email": "ana@otra.test", "org_id": "otra", "role": "EMPLOYEE", "activo": False,
         "aegis_user_id": OTRO},
        {"_id": "3", "user": "h1", "email": "h@h.com", "org_id": "herramientas-y-moldes-industriales", "role": "EMPLOYEE", "activo": False},
        {"_id": "4", "user": "h2", "email": "h2@h.com", "org_id": "herramientas_y_moldes_industriales", "role": "ADMIN", "activo": False},
    ])
    assert plan["aplicado"] is False
    assert any("alias_igual_en_otro_dominio" in f["conflictos"] for f in plan["filas"])
    inactiva = next(f for f in plan["filas"] if f["vinculo_local"] == "2")
    assert inactiva["activo"] is False
    assert inactiva["rol_propuesto"] == "EMPLOYEE"
    assert plan["notas"]


def test_acceso_de_otra_empresa_o_app_no_habilita_negocio():
    perfil = _perfil()
    assert misma_empresa_y_app(perfil, _acceso(tenant="00000000-0000-0000-0000-000000000000")) is False
    ajeno = dict(_acceso())
    ajeno["app_key"] = "principal"
    assert misma_empresa_y_app(perfil, ajeno) is False
    assert misma_empresa_y_app(perfil, _acceso(allowed=False)) is False


def test_cuenta_inactiva_no_entra(monkeypatch):
    _preparar(monkeypatch, roles=["empleado"])
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({
        "user": "ana", "org_id": "acme", "role": "EMPLOYEE", "activo": False,
        "aegis_user_id": USUARIO, "aegis_tenant_id": TENANT,
    })
    _resp, codigo = _entrar(mongo)
    assert codigo == 403


def test_must_change_bloquea_negocio_aunque_no_haya_pantalla(monkeypatch):
    monkeypatch.setattr("core.aegis_config.get_aegis_settings", lambda: {"login_enabled": False})
    from core.controles_request import aplicar
    mongo = FakeMongo()
    app = Flask(__name__)
    with app.test_request_context("/empleados", method="GET"):
        sesion = crear(
            mongo, user="ana", org_id="acme",
            claims={"user": "ana", "role": "EMPLOYEE", "org_id": "acme", "plataforma": False},
            must_change_password=True, minutos=15,
        )
        g.org_id = None
        bloqueo = aplicar(mongo, {"sid": sesion["sid"], "user": "ana", "org_id": "acme", "role": "EMPLOYEE"})
    assert bloqueo[1] == 403


def test_cliente_no_cambia_de_empresa_en_la_sesion(monkeypatch):
    monkeypatch.setattr("core.aegis_config.get_aegis_settings", lambda: {"login_enabled": False})
    from core.controles_request import aplicar
    mongo = FakeMongo()
    app = Flask(__name__)
    with app.test_request_context("/empleados", method="POST", json={"org_id": "otra"}):
        sesion = crear(
            mongo, user="ana", org_id="acme",
            claims={"user": "ana", "role": "EMPLOYEE", "org_id": "acme", "plataforma": False},
            minutos=15,
        )
        bloqueo = aplicar(mongo, {"sid": sesion["sid"], "user": "ana", "org_id": "acme", "role": "EMPLOYEE"})
    assert bloqueo[1] == 403


def test_cache_de_acceso_tiene_ventana_y_no_afirma_revocacion_instantanea():
    ahora = datetime.now(timezone.utc)
    sesion = {"auth_checked_at": ahora.isoformat()}
    assert acceso_en_cache(sesion, ahora=ahora + timedelta(seconds=30), segundos=60) is True
    assert acceso_en_cache(sesion, ahora=ahora + timedelta(seconds=61), segundos=60) is False


def test_refresh_rechazado_no_alarga_la_sesion():
    mongo = FakeMongo()
    sesion = crear(
        mongo, user="ana", org_id="acme",
        claims={"user": "ana", "role": "EMPLOYEE", "org_id": "acme"},
        aegis={"refresh_token": "viejo", "access_token": "a", "user_id": USUARIO, "tenant_id": TENANT},
        minutos=15,
    )
    assert rotar(mongo, sesion["sid"], 0, {"access_token": "nuevo", "refresh_token": "par-nuevo"}) is True
    assert rotar(mongo, sesion["sid"], 0, {"access_token": "tarde", "refresh_token": "par-tarde"}) is False
    guardada = mongo.db.sesiones.find_one({"sid": sesion["sid"]})
    assert guardada["refresh_token"] == "par-nuevo"
    assert guardada["gen"] == 1


def test_contrasena_exige_clases_dentro_del_limite_de_openapi():
    assert contrasena_aceptable("Abcdef123456!")
    assert not contrasena_aceptable("Abcdef123456")
    assert not contrasena_aceptable("Corta1!")
    assert not contrasena_aceptable("A" * 257)


def test_clave_tecnica_no_cambia_de_tenant(monkeypatch):
    monkeypatch.setattr(
        "core.aegis_client.get_aegis_settings",
        lambda: {"tenant_id": "cibercom", "app_id": "empleados", "api_key": "x", "admin_enabled": True, "base_url": "https://aegis.example", "timeout": 1},
    )
    assert alcance_de_clave("cibercom") is None
    cuerpo, status = alcance_de_clave("otra-empresa")
    assert status == 403
    assert "no cubre" in cuerpo["error"]


def test_rutas_privadas_fallan_sin_contexto_y_no_mudan_empresa():
    raw = FakeMongo().db
    db = BaseDatosMultiTenant(raw)
    app = Flask(__name__)
    with app.test_request_context():
        g.contexto_privado = True
        g.org_id = None
        try:
            db.empleados.find({})
            assert False, "debía fallar"
        except ContextoEmpresaFaltante:
            pass
        g.org_id = "empresa-a"
        db.empleados.insert_one({"Nombre": "A"})
        db.empleados.update_one({"Nombre": "A"}, {"$set": {"org_id": "empresa-b", "Nombre": "A"}})
    assert raw.empleados.find_one({})["org_id"] == "empresa-a"
    with app.test_request_context():
        g.org_id = "empresa-a"
        vistos = {}

        class Col:
            def aggregate(self, pipeline, *a, **k):
                vistos["pipeline"] = pipeline
                return []

        class DB:
            empleados = Col()

        BaseDatosMultiTenant(DB()).empleados.aggregate([
            {"$lookup": {"from": "rh", "localField": "id", "foreignField": "empleado_id", "as": "rh"}},
        ])
        assert vistos["pipeline"][1]["$lookup"]["pipeline"][0] == {"$match": {"org_id": "empresa-a"}}


def test_solicitud_valida_reintento_rol_y_caida(monkeypatch):
    import api.acceso.solicitudes as solicitudes
    from core.public_rate_limit import RegistrationRateLimiter
    solicitudes._limite = RegistrationRateLimiter(max_attempts=20, window_seconds=3600)
    mongo = FakeMongo()
    mongo.db.usuario.insert_one({"email": "ana@acme.test", "org_id": "acme", "role": "EMPLOYEE"})
    app = Flask(__name__)
    with app.test_request_context():
        ok, status = crear_solicitud(mongo, {
            "empresa": "Acme", "contacto": "Ana Ruiz", "correo": "ana@acme.test",
        }, "10.0.0.8", "clave-1")
        otra, status2 = crear_solicitud(mongo, {
            "empresa": "Acme", "contacto": "Ana Ruiz", "correo": "ana@acme.test", "role": "admin",
        }, "10.0.0.8", "clave-2")
        reintento, status3 = crear_solicitud(mongo, {
            "empresa": "Acme", "contacto": "Ana Ruiz", "correo": "ana@acme.test",
        }, "10.0.0.9", "clave-1")
    assert status == 202 and status3 == 202
    assert status2 == 400
    assert ok.get_json()["message"] == reintento.get_json()["message"]
    assert "ana@acme.test" not in ok.get_json()["message"]
    assert mongo.db.solicitudes_acceso.count_documents({}) == 1
    assert mongo.db.usuario.count_documents({}) == 1
    assert otra.get_json()["error"]
    guardada = mongo.db.solicitudes_acceso.find_one({})
    assert "role" not in guardada and guardada["producto"] == "empleados"

    def falla(*_a, **_k):
        raise RuntimeError("disco")

    mongo.db.solicitudes_acceso.insert_one = falla
    with app.test_request_context():
        caida, status4 = crear_solicitud(mongo, {
            "empresa": "Otra", "contacto": "Luis Paz", "correo": "luis@otra.test",
        }, "10.0.0.7", "clave-3")
    assert status4 == 503
    assert caida.get_json().get("message") != ok.get_json()["message"]


def test_abuso_de_solicitudes_se_limita():
    import api.acceso.solicitudes as solicitudes
    from core.public_rate_limit import RegistrationRateLimiter
    solicitudes._limite = RegistrationRateLimiter(max_attempts=2, window_seconds=3600)
    mongo = FakeMongo()
    app = Flask(__name__)
    codigos = []
    with app.test_request_context():
        for n in range(3):
            _resp, status = crear_solicitud(mongo, {
                "empresa": f"Empresa {n}", "contacto": "Ana Ruiz", "correo": f"ana{n}@acme.test",
            }, "10.1.1.1", f"k-{n}")
            codigos.append(status)
    assert codigos[:2] == [202, 202]
    assert codigos[2] == 429


def test_operador_de_empresa_no_ve_solicitudes_y_aprobar_no_crea_acceso(monkeypatch):
    monkeypatch.setattr("api.tenants.routes.get_aegis_settings", lambda: {"tenant_id": "cibercom"})
    from api.acceso import setup_acceso_routes
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    setup_acceso_routes(app, mongo)
    cliente = app.test_client()
    with app.app_context():
        token_empresa = create_access_token(identity="admin", additional_claims={
            "user": "admin", "role": "SUPER_ADMIN", "org_id": "acme", "plataforma": False,
        })
        token_plataforma = create_access_token(identity="ops", additional_claims={
            "user": "ops", "role": "SUPER_ADMIN", "org_id": "cibercom", "plataforma": True,
        })
    assert cliente.get("/admin/access-requests", headers={"Authorization": f"Bearer {token_empresa}"}).status_code == 403
    with app.test_request_context():
        _resp, status = crear_solicitud(mongo, {
            "empresa": "Nueva", "contacto": "Ada Lopez", "correo": "ada@nueva.test",
        }, "10.2.2.2", "sol-1")
    assert status == 202
    identificador = mongo.db.solicitudes_acceso.find_one({})["id_publico"]
    respuesta = cliente.post(f"/admin/access-requests/{identificador}", headers={"Authorization": f"Bearer {token_plataforma}"}, json={
        "estado": "aprobada",
        "identificadores": {"aegis_tenant_id": TENANT, "aegis_user_id": USUARIO, "org_id": "nueva"},
        "nota": "Alta hecha en la consola",
    })
    assert respuesta.status_code == 200
    assert mongo.db.usuario.count_documents({}) == 0
    assert listar(mongo)[0]["estado"] == "aprobada"
    assert listar(mongo)[0]["aegis_user_id"] == USUARIO
