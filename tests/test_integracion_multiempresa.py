# tests/test_integracion_multiempresa.py
# ─────────────────────────────────────────────────────────────────────────────
# Prueba de INTEGRACIÓN (no usa FakeMongo — corre contra el Mongo real de
# este entorno, con app.py real: JWT, multi-tenencia y rutas reales). Simula
# el uso normal del sistema por una empresa cliente cualquiera ("empresa_qa"):
#
#   1. Su SUPER_ADMIN se auto-aprovisiona (igual que en el login real) SIN
#      quedar vinculado a un empleado.
#   2. Su ADMIN y su EMPLOYEE sí tienen empleado_id + ficha de RH — uso
#      normal, como pidió el cliente: "los usuarios operativos que tengan un
#      rol en la empresa y los empleados deben poderse dar de alta en RH".
#   3. GET /empleados (Organigrama + tabla RH) del ADMIN de esa empresa ve
#      SOLO su propia gente — nunca la de Cibercom ni la de otra empresa — y
#      NUNCA a su propio SUPER_ADMIN.
#   4. GET /admin/tenants con el SUPER_ADMIN de "empresa_qa" → 403: no es
#      Cibercom, no puede ver el registro central de empresas.
#   5. GET /admin/tenants con un SUPER_ADMIN de Cibercom → 200.
#
# Todo lo insertado se borra al final (éxito o falla) — no debe quedar rastro
# de "empresa_qa" en la base real.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone
from bson.objectid import ObjectId
from flask_jwt_extended import create_access_token

import app as flask_app_module
from core.aegis_config import get_aegis_settings

app = flask_app_module.app
mongo = flask_app_module.mongo

ORG_ID = "qa_empresa_prueba_unitaria"  # prefijo inconfundible, nunca usado por una empresa real
TENANT_CIBERCOM = get_aegis_settings()["tenant_id"] or "cibercom"


def _jwt_para(user, role, empleado_id="", org_id=ORG_ID, areas=None):
    with app.app_context():
        return create_access_token(identity=user, additional_claims={
            "user": user, "role": role, "empleado_id": empleado_id or "",
            "org_id": org_id, "areas_administradas": areas or [],
        })


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def empresa_qa():
    """
    Levanta una empresa completa de punta a punta contra Mongo real (raw,
    sin depender de g.org_id): un SUPER_ADMIN sin empleado, un ADMIN y un
    EMPLOYEE con su ficha de RH — el "uso normal" que pidió el cliente.
    Borra TODO lo que crea al terminar, pase o falle la prueba.
    """
    raw = mongo.db.raw
    creados = {"usuario": [], "empleados": [], "rh": []}

    def _crear_empleado(nombre, apellido, depto):
        _id = raw.empleados.insert_one({
            "Nombre": nombre, "ApelPaterno": apellido, "depto_id": depto,
            "estado": "activo", "org_id": ORG_ID,
        }).inserted_id
        creados["empleados"].append(_id)
        return _id

    def _crear_rh(empleado_id, puesto):
        rh_id = raw.rh.insert_one({
            "empleado_id": empleado_id, "Puesto": puesto, "org_id": ORG_ID,
        }).inserted_id
        creados["rh"].append(rh_id)

    def _crear_usuario(user, role, empleado_id=None):
        uid = raw.usuario.insert_one({
            "user": user, "role": role, "empleado_id": empleado_id,
            "org_id": ORG_ID,
        }).inserted_id
        creados["usuario"].append(uid)
        return uid

    eid_admin = _crear_empleado("Ana", "Operativa", "VENTAS")
    _crear_rh(eid_admin, "Gerente de Ventas")
    _crear_usuario("qa_admin", "ADMIN", eid_admin)

    eid_empleado = _crear_empleado("Beto", "DePlantilla", "VENTAS")
    _crear_rh(eid_empleado, "Ejecutivo de Ventas")
    _crear_usuario("qa_empleado", "EMPLOYEE", eid_empleado)

    # El SUPER_ADMIN se auto-aprovisiona SIN empleado_id — mismo patrón que
    # api/login/logic.py al dar de alta el primero de una empresa nueva.
    _crear_usuario("qa_super_admin", "SUPER_ADMIN", None)

    # Registro central de la empresa (lo que hoy hace registrar_tenant()).
    tenant_reg_id = raw.tenants.insert_one({
        "org_id": ORG_ID, "nombre": "Empresa QA de Prueba", "estado": "activo",
        "fecha_alta": datetime.now(timezone.utc).isoformat(),
    }).inserted_id

    yield {"eid_admin": eid_admin, "eid_empleado": eid_empleado}

    # ── Limpieza total, pase lo que pase en la prueba ──────────────────────
    for uid in creados["usuario"]:
        raw.usuario.delete_one({"_id": uid})
    for eid in creados["empleados"]:
        raw.empleados.delete_one({"_id": eid})
    for rid in creados["rh"]:
        raw.rh.delete_one({"_id": rid})
    raw.tenants.delete_one({"_id": tenant_reg_id})

    # Cinturón y tirantes: por si algo se coló con otro _id, nunca debe
    # quedar NADA con este org_id en ninguna colección tocada por la prueba.
    for coleccion in ("usuario", "empleados", "rh", "tenants"):
        getattr(raw, coleccion).delete_many({"org_id": ORG_ID})


def test_admin_de_la_empresa_ve_solo_su_propia_gente_y_nunca_a_su_super_admin(client, empresa_qa):
    token = _jwt_para("qa_admin", "ADMIN", str(empresa_qa["eid_admin"]), areas=["VENTAS"])
    resp = client.get("/empleados", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    nombres = {e["Nombre"] for e in resp.get_json()}
    assert nombres == {"Ana", "Beto"}  # su ADMIN y su EMPLOYEE, uso normal
    assert "SUPER_ADMIN" not in str(resp.get_json())  # el super admin nunca aparece como empleado


def test_super_admin_de_empresa_cliente_no_puede_ver_registro_de_empresas(client, empresa_qa):
    token = _jwt_para("qa_super_admin", "SUPER_ADMIN")
    resp = client.get("/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_admin_de_empresa_cliente_tampoco_puede_ver_registro_de_empresas(client, empresa_qa):
    """Ni siquiera intentando con el rol equivocado además del tenant equivocado."""
    token = _jwt_para("qa_admin", "ADMIN", str(empresa_qa["eid_admin"]))
    resp = client.get("/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_super_admin_de_cibercom_si_puede_ver_registro_de_empresas(client, empresa_qa):
    token = _jwt_para("op_cibercom_qa", "SUPER_ADMIN", org_id=TENANT_CIBERCOM)
    resp = client.get("/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_sin_token_no_hay_acceso(client):
    resp = client.get("/admin/tenants")
    assert resp.status_code == 401


def test_no_quedo_nada_de_la_empresa_qa_despues_de_las_pruebas():
    """Corre DESPUÉS de que el fixture empresa_qa ya hizo su teardown en las
    pruebas anteriores (pytest ejecuta los tests del archivo en orden) —
    confirma en Mongo real que no sobrevivió ningún documento."""
    raw = mongo.db.raw
    for coleccion in ("usuario", "empleados", "rh", "tenants"):
        restantes = list(getattr(raw, coleccion).find({"org_id": ORG_ID}))
        assert restantes == [], f"Quedaron documentos sin borrar en {coleccion}: {restantes}"
