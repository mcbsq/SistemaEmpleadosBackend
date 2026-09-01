from scripts.backfill_cibercom_tenant import backfill
from tests.fakes import FakeMongo


def test_dry_run_reports_without_writing():
    db = FakeMongo().db
    db.empleados.insert_one({"Nombre": "Histórico"})

    report = backfill(db, ["empleados"], "cibercom", apply=False)

    assert report["empleados"]["before"]["without_org"] == 1
    assert report["empleados"]["updated"] == 0
    assert db.empleados.find_one({"Nombre": "Histórico"}).get("org_id") is None


def test_apply_updates_only_missing_org_and_is_idempotent():
    db = FakeMongo().db
    db.empleados.insert_one({"Nombre": "Histórico"})
    db.empleados.insert_one({"Nombre": "Otro", "org_id": "otra"})

    first = backfill(db, ["empleados"], "cibercom", apply=True)
    second = backfill(db, ["empleados"], "cibercom", apply=True)

    assert first["empleados"]["updated"] == 1
    assert second["empleados"]["updated"] == 0
    assert db.empleados.count_documents({}) == 2
    assert db.empleados.find_one({"Nombre": "Histórico"})["org_id"] == "cibercom"
    assert db.empleados.find_one({"Nombre": "Otro"})["org_id"] == "otra"


def test_apply_bootstraps_cibercom_catalog_and_config_without_duplicates():
    db = FakeMongo().db

    backfill(db, ["empleados"], "cibercom", apply=True)
    backfill(db, ["empleados"], "cibercom", apply=True)

    assert db.tenants.count_documents({"org_id": "cibercom"}) == 1
    assert db.organizacion.count_documents({"org_id": "cibercom"}) == 1
    assert db.tenants.find_one({"org_id": "cibercom"})["estado"] == "activo"
