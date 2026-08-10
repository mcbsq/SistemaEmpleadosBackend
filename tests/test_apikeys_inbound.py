# tests/test_apikeys_inbound.py
# ─────────────────────────────────────────────────────────────────────────────
# API keys ENTRANTES (api/apikeys/ + core/apikey_auth.py) — otro sistema nos
# pide una key a NOSOTROS para leer datos vía /api/v1/... Prueba real:
# generar una key, guardarla (hasheada), y validar que el decorador
# require_api_key SÍ deja pasar con la key correcta y NIEGA con cualquier otra.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask

from tests.fakes import FakeMongo
from api.apikeys.logic import crear_api_key
from core.apikey_auth import require_api_key, generar_api_key


@pytest.fixture
def mongo():
    return FakeMongo()


@pytest.fixture(autouse=True)
def app_context():
    """jsonify() exige un contexto de aplicación aunque se llame la función
    de lógica directamente (fuera de una request real)."""
    bare_app = Flask(__name__)
    with bare_app.app_context():
        yield


@pytest.fixture
def app(mongo):
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/v1/empleados")
    @require_api_key(mongo, "empleados:read")
    def empleados_route():
        return {"empleados": []}, 200

    @app.route("/api/v1/ping")
    @require_api_key(mongo)  # sin scopes exigidos — cualquier key activa pasa
    def ping_route():
        return {"pong": True}, 200

    return app


def test_generar_api_key_produce_hash_verificable():
    """El hash guardado debe coincidir SOLO con el plaintext que lo generó."""
    plaintext, key_hash = generar_api_key()

    esperado_prefijo = "sk_live_"
    assert plaintext.startswith(esperado_prefijo), (
        f"esperado: prefijo '{esperado_prefijo}', real: '{plaintext[:8]}'"
    )

    from core.apikey_auth import _hash_key
    assert _hash_key(plaintext) == key_hash, "el hash no coincide con su propio plaintext"
    assert _hash_key("cualquier-otro-valor") != key_hash, "un plaintext distinto no debería producir el mismo hash"


def test_crear_api_key_guarda_solo_el_hash_nunca_el_plaintext(mongo):
    """La API key creada debe:
    1) devolver el plaintext UNA vez en la respuesta HTTP,
    2) pero en Mongo solo debe quedar el hash, nunca el valor real."""
    resp, status = crear_api_key(mongo, {"nombre": "Sistema Nómina Externo", "scopes": ["empleados:read"]}, "superadmin_test")
    body = resp.get_json()

    assert status == 201, f"esperado: 201, real: {status}"
    assert "key" in body and body["key"].startswith("sk_live_"), "la respuesta debe traer el plaintext una vez"

    guardado = mongo.db.api_keys.find_one({"nombre": "Sistema Nómina Externo"})
    assert guardado is not None, "la key debería haberse guardado en Mongo"
    assert "key_hash" in guardado, "debe guardarse el hash"
    assert guardado["key_hash"] != body["key"], "el hash NUNCA debe ser igual al plaintext"
    assert "key" not in guardado, "el documento en Mongo no debe tener el campo plaintext"


def test_endpoint_protegido_acepta_key_valida_con_scope_correcto(app, mongo):
    resp, status = crear_api_key(mongo, {"nombre": "Consumidor A", "scopes": ["empleados:read"]}, "superadmin_test")
    plaintext = resp.get_json()["key"]

    client = app.test_client()
    r = client.get("/api/v1/empleados", headers={"Authorization": f"ApiKey {plaintext}"})

    assert r.status_code == 200, f"esperado: 200 con key válida y scope correcto, real: {r.status_code} — {r.get_json()}"
    assert r.get_json() == {"empleados": []}


def test_endpoint_protegido_rechaza_key_invalida(app, mongo):
    crear_api_key(mongo, {"nombre": "Consumidor A", "scopes": ["empleados:read"]}, "superadmin_test")

    client = app.test_client()
    r = client.get("/api/v1/empleados", headers={"Authorization": "ApiKey sk_live_esto-no-existe-en-mongo"})

    assert r.status_code == 401, f"esperado: 401 (key inexistente), real: {r.status_code}"
    assert r.get_json()["code"] == "invalid_key"


def test_endpoint_protegido_rechaza_sin_header(app):
    client = app.test_client()
    r = client.get("/api/v1/empleados")
    assert r.status_code == 401, f"esperado: 401 (falta header), real: {r.status_code}"
    assert r.get_json()["code"] == "missing_key"


def test_endpoint_protegido_rechaza_key_sin_el_scope_requerido(app, mongo):
    """Key válida pero creada SOLO con scope 'rh:read' — no debe poder leer
    /api/v1/empleados, que exige 'empleados:read'."""
    resp, _ = crear_api_key(mongo, {"nombre": "Consumidor limitado", "scopes": ["rh:read"]}, "superadmin_test")
    plaintext = resp.get_json()["key"]

    client = app.test_client()
    r = client.get("/api/v1/empleados", headers={"Authorization": f"ApiKey {plaintext}"})

    assert r.status_code == 403, f"esperado: 403 (scope insuficiente), real: {r.status_code}"
    assert r.get_json()["code"] == "forbidden_scope"


def test_key_desactivada_deja_de_funcionar(app, mongo):
    resp, _ = crear_api_key(mongo, {"nombre": "Consumidor B", "scopes": ["empleados:read"]}, "superadmin_test")
    plaintext = resp.get_json()["key"]
    doc_id = resp.get_json()["_id"]

    # Confirma que SÍ funcionaba antes de desactivar (control positivo).
    client = app.test_client()
    r_antes = client.get("/api/v1/empleados", headers={"Authorization": f"ApiKey {plaintext}"})
    assert r_antes.status_code == 200, "la key debía funcionar antes de desactivarla"

    from bson.objectid import ObjectId
    mongo.db.api_keys.update_one({"_id": ObjectId(doc_id)}, {"$set": {"activa": False}})

    r_despues = client.get("/api/v1/empleados", headers={"Authorization": f"ApiKey {plaintext}"})
    assert r_despues.status_code == 401, f"esperado: 401 tras desactivar, real: {r_despues.status_code}"


def test_uso_incrementa_contador_y_ultimo_uso(app, mongo):
    resp, _ = crear_api_key(mongo, {"nombre": "Consumidor C", "scopes": ["empleados:read"]}, "superadmin_test")
    plaintext = resp.get_json()["key"]
    doc_id = resp.get_json()["_id"]

    client = app.test_client()
    client.get("/api/v1/ping", headers={"Authorization": f"ApiKey {plaintext}"})
    client.get("/api/v1/ping", headers={"Authorization": f"ApiKey {plaintext}"})

    from bson.objectid import ObjectId
    doc = mongo.db.api_keys.find_one({"_id": ObjectId(doc_id)})
    assert doc["usos_totales"] == 2, f"esperado: 2 usos, real: {doc['usos_totales']}"
    assert doc["ultimo_uso"] is not None, "ultimo_uso debe quedar registrado tras el primer uso"
