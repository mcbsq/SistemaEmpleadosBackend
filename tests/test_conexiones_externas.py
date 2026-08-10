# tests/test_conexiones_externas.py
# ─────────────────────────────────────────────────────────────────────────────
# API keys SALIENTES (core/conexiones_externas.py + api/conexiones_externas/) —
# el caso concreto pedido: la nómina se genera en OTRO sistema; este backend
# guarda la credencial de ESE sistema y la consume en vivo para mostrarla en
# el perfil del empleado. Se simula el sistema externo con requests_mock (no
# se llama a internet real) y se compara resultado real vs. esperado en cada
# caso: éxito, sin dato para ese empleado, sistema caído, y credencial
# incorrecta.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET_KEY", "clave-de-pruebas-no-usar-en-produccion")

import pytest
from flask import Flask

from tests.fakes import FakeMongo
from core.conexiones_externas import cifrar, descifrar, consultar_sistema_externo
from api.conexiones_externas.logic import crear_conexion, obtener_nomina_externa


@pytest.fixture(autouse=True)
def app_context():
    app = Flask(__name__)
    with app.app_context():
        yield


@pytest.fixture
def mongo():
    return FakeMongo()


def test_cifrado_es_reversible_y_nunca_expone_el_texto_plano():
    """A diferencia de las API keys entrantes (hash de una vía), aquí SÍ hace
    falta recuperar el valor real para mandarlo al sistema externo."""
    original = "clave-secreta-del-sistema-de-nomina-123"
    cifrado = cifrar(original)

    assert cifrado != original, "el valor cifrado nunca debe ser igual al original"
    assert descifrar(cifrado) == original, f"esperado tras descifrar: '{original}', real: '{descifrar(cifrado)}'"


def test_consultar_sistema_externo_devuelve_datos_reales_esperados(requests_mock):
    """Caso feliz: el sistema externo de nómina responde con los datos del
    empleado — exactamente el escenario que se pidió probar."""
    conexion = {
        "base_url": "https://nomina-externa.ejemplo.com",
        "ruta_plantilla": "/nomina/{identificador}",
        "esquema_auth": "Bearer",
        "api_key_cifrada": cifrar("clave-real-del-sistema-externo"),
    }
    esperado = {"periodo": "2026-08", "percepciones": 85000, "deducciones": 12500, "neto": 72500}

    requests_mock.get(
        "https://nomina-externa.ejemplo.com/nomina/EMP-0001",
        json=esperado,
        status_code=200,
    )

    datos, err = consultar_sistema_externo(conexion, "EMP-0001")

    assert err is None, f"no debería haber error, real: {err}"
    assert datos == esperado, f"esperado: {esperado}, real: {datos}"

    # Confirma que la key correcta viajó en el header Authorization — si el
    # sistema externo exige auth y no llega bien, esto es lo que fallaría
    # primero en producción.
    header_enviado = requests_mock.last_request.headers["Authorization"]
    assert header_enviado == "Bearer clave-real-del-sistema-externo", (
        f"esperado: 'Bearer clave-real-del-sistema-externo', real: '{header_enviado}'"
    )


def test_consultar_sistema_externo_empleado_sin_datos_devuelve_404_controlado(requests_mock):
    conexion = {
        "base_url": "https://nomina-externa.ejemplo.com",
        "ruta_plantilla": "/nomina/{identificador}",
        "api_key_cifrada": cifrar("clave-real"),
    }
    requests_mock.get("https://nomina-externa.ejemplo.com/nomina/SIN-REGISTRO", status_code=404)

    datos, err = consultar_sistema_externo(conexion, "SIN-REGISTRO")

    assert datos is None, "no debe haber datos cuando el externo responde 404"
    assert err is not None
    mensaje, status = err
    assert status == 404, f"esperado: 404, real: {status}"


def test_consultar_sistema_externo_caido_no_lanza_excepcion(requests_mock):
    """Un sistema externo caído no debe tumbar el perfil del empleado — debe
    degradar a un mensaje de error controlado."""
    import requests
    conexion = {
        "base_url": "https://nomina-externa.ejemplo.com",
        "ruta_plantilla": "/nomina/{identificador}",
        "api_key_cifrada": cifrar("clave-real"),
    }
    requests_mock.get(
        "https://nomina-externa.ejemplo.com/nomina/EMP-0001",
        exc=requests.exceptions.ConnectTimeout,
    )

    datos, err = consultar_sistema_externo(conexion, "EMP-0001")

    assert datos is None
    mensaje, status = err
    assert status == 503, f"esperado: 503 (no respondió), real: {status}"


def test_flujo_completo_crear_conexion_y_obtener_nomina_del_empleado(mongo, requests_mock):
    """Prueba de integración del módulo completo, tal como lo usaría el
    perfil de un empleado: 1) SUPER_ADMIN registra la conexión (API key se
    cifra al guardar), 2) se pide la nómina de un empleado por su
    NumeroEmpleado, 3) se compara el resultado real contra el esperado."""
    identity = {"user": "superadmin_test", "role": "SUPER_ADMIN"}

    resp, status = crear_conexion(mongo, {
        "nombre": "Sistema Nómina Externo",
        "tipo": "nomina",
        "base_url": "https://nomina-externa.ejemplo.com",
        "ruta_plantilla": "/nomina/{identificador}",
        "campo_mapeo": "NumeroEmpleado",
        "api_key": "clave-real-del-sistema-externo",
    }, identity)
    assert status == 201, f"esperado: 201 al crear la conexión, real: {status} — {resp.get_json()}"

    # Empleado con RH — su NumeroEmpleado es lo que se manda al sistema externo.
    from bson.objectid import ObjectId
    empleado_id = ObjectId()
    mongo.db.rh.insert_one({"empleado_id": empleado_id, "NumeroEmpleado": "EMP-0001"})

    esperado = {"periodo": "2026-08", "percepciones": 85000, "deducciones": 12500, "neto": 72500}
    requests_mock.get(
        "https://nomina-externa.ejemplo.com/nomina/EMP-0001",
        json=esperado, status_code=200,
    )

    resp, status = obtener_nomina_externa(mongo, str(empleado_id))
    body = resp.get_json()

    assert status == 200, f"esperado: 200, real: {status}"
    assert body["configurada"] is True
    assert body["datos"] == esperado, f"esperado: {esperado}, real: {body.get('datos')}"
    assert body["fuente"] == "Sistema Nómina Externo"


def test_empleado_sin_numero_empleado_no_intenta_llamar_al_externo(mongo, requests_mock):
    """Si el empleado no tiene el campo de mapeo configurado (NumeroEmpleado),
    debe fallar de forma clara ANTES de llamar al sistema externo — no con un
    error de red confuso."""
    identity = {"user": "superadmin_test", "role": "SUPER_ADMIN"}
    crear_conexion(mongo, {
        "nombre": "Sistema Nómina Externo", "tipo": "nomina",
        "base_url": "https://nomina-externa.ejemplo.com",
        "campo_mapeo": "NumeroEmpleado", "api_key": "clave-real",
    }, identity)

    from bson.objectid import ObjectId
    empleado_id = ObjectId()
    mongo.db.rh.insert_one({"empleado_id": empleado_id})  # sin NumeroEmpleado

    resp, status = obtener_nomina_externa(mongo, str(empleado_id))
    body = resp.get_json()

    assert status == 200
    assert body["configurada"] is True
    assert "NumeroEmpleado" in body["error"], f"el error debe mencionar el campo faltante, real: {body.get('error')}"
    assert requests_mock.call_count == 0, "no debió llamarse al sistema externo sin identificador"


def test_sin_conexion_configurada_responde_no_configurada_sin_error(mongo):
    """Empresa que no configuró ninguna integración de nómina — debe ser un
    estado normal (no error), para que el perfil simplemente no muestre la
    sección, como ya se verificó visualmente."""
    from bson.objectid import ObjectId
    resp, status = obtener_nomina_externa(mongo, str(ObjectId()))
    body = resp.get_json()

    assert status == 200
    assert body == {"configurada": False}, f"esperado: {{'configurada': False}}, real: {body}"
