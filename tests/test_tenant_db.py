from flask import Flask, g

from core.tenant_db import BaseDatosMultiTenant
from tests.fakes import FakeMongo


def _context():
    return Flask(__name__).test_request_context()


def test_filter_cannot_replace_current_tenant():
    raw = FakeMongo().db
    db = BaseDatosMultiTenant(raw)
    raw.empleados.insert_one({"Nombre": "A", "org_id": "empresa-a"})
    raw.empleados.insert_one({"Nombre": "B", "org_id": "empresa-b"})

    with _context():
        g.org_id = "empresa-a"
        assert db.empleados.find_one({"Nombre": "B", "org_id": "empresa-b"}) is None
        assert db.empleados.find_one({"Nombre": "A", "org_id": "empresa-b"})["Nombre"] == "A"


def test_insert_and_replace_enforce_current_tenant():
    raw = FakeMongo().db
    db = BaseDatosMultiTenant(raw)

    with _context():
        g.org_id = "empresa-a"
        result = db.empleados.insert_one({"Nombre": "A", "org_id": "empresa-b"})
        db.empleados.replace_one(
            {"_id": result.inserted_id},
            {"Nombre": "Actualizado", "org_id": "empresa-b"},
        )

    saved = raw.empleados.find_one({"_id": result.inserted_id})
    assert saved["Nombre"] == "Actualizado"
    assert saved["org_id"] == "empresa-a"


def test_upsert_enforces_tenant_in_filter_and_inserted_document():
    raw = FakeMongo().db
    db = BaseDatosMultiTenant(raw)

    with _context():
        g.org_id = "empresa-a"
        db.organizacion.update_one(
            {"org_id": "empresa-b"},
            {"$set": {"name": "A"}, "$setOnInsert": {"org_id": "empresa-b"}},
            upsert=True,
        )

    assert raw.organizacion.find_one({"org_id": "empresa-a"})["name"] == "A"
    assert raw.organizacion.find_one({"org_id": "empresa-b"}) is None
