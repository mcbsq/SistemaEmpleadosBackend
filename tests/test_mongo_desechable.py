# Semántica de lease e índices sobre un Mongo desechable.
# No lee MONGO_URI del proyecto. Si no hay servidor en 127.0.0.1:27028, se omite.
import uuid

import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from scripts.migracion_indices_aegis import aplicar_indices

URI = "mongodb://127.0.0.1:27028/desechable"


def _cliente():
    cliente = MongoClient(URI, serverSelectionTimeoutMS=800)
    try:
        cliente.admin.command("ping")
    except ServerSelectionTimeoutError:
        pytest.skip("No hay Mongo desechable en 127.0.0.1:27028")
    nombre = cliente.get_default_database().name
    assert "desechable" in nombre
    return cliente


@pytest.fixture()
def db():
    cliente = _cliente()
    base = cliente.get_default_database()
    base.client.drop_database(base.name)
    yield base
    base.client.drop_database(base.name)
    cliente.close()


def test_lease_un_ganador_vencimiento_y_fallo_tras_rotar(db):
    from datetime import datetime, timedelta, timezone
    import core.sesiones as sesiones

    class _Raw:
        def __init__(self, base):
            self.sesiones = base.sesiones
            self.organizacion = base.organizacion
            self.usuario = base.usuario

    class _Mongo:
        def __init__(self, base):
            self.db = self
            self.raw = _Raw(base)

    mongo = _Mongo(db)
    momento = {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    original = sesiones.ahora
    sesiones.ahora = lambda: momento["t"]
    try:
        sid = "sid-desechable"
        db.sesiones.insert_one({
            "sid": sid, "gen": 0, "revocada": False, "lease_hasta": None,
            "refresh_token": "refresh-1", "access_token": "acceso-1",
            "expira_en": "2099-01-01T00:00:00+00:00",
            "auth_checked_at": (momento["t"] - timedelta(minutes=5)).isoformat(),
        })
        primero, dueno = sesiones.reclamar_lease(mongo, sid, 0, segundos=30)
        assert dueno
        segundo, nada = sesiones.reclamar_lease(mongo, sid, 0, segundos=30)
        assert segundo is None and nada is None
        ok, _expira = sesiones.confirmar_par(
            mongo, sid, 0, dueno,
            {"access_token": "acceso-2", "refresh_token": "refresh-2"}, 15,
        )
        assert ok
        guardada = db.sesiones.find_one({"sid": sid})
        assert guardada["refresh_token"] == "refresh-2"
        assert guardada["acceso_pendiente"] is True
        assert sesiones.acceso_en_cache(guardada, segundos=60) is False
        momento["t"] += timedelta(seconds=31)
        db.sesiones.update_one({"sid": sid}, {"$set": {"gen": 1, "lease_hasta": momento["t"].isoformat(), "lease_dueno": "muerto"}})
        momento["t"] += timedelta(seconds=5)
        _previo, retomado = sesiones.reclamar_lease(mongo, sid, 1, segundos=10)
        assert retomado
        assert db.sesiones.find_one({"sid": sid})["lease_dueno"] == retomado
    finally:
        sesiones.ahora = original


def _reclamar_mongo(cola):
    import os
    import sys
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from pymongo import MongoClient as Cliente
    from core.sesiones import reclamar_lease

    class Raw:
        def __init__(self, base):
            self.sesiones = base.sesiones

    class Mongo:
        def __init__(self, base):
            self.db = self
            self.raw = Raw(base)

    cliente = Cliente(URI, serverSelectionTimeoutMS=2000)
    base = cliente.get_default_database()
    _doc, dueno = reclamar_lease(Mongo(base), "sid-procesos", 0)
    cola.put(dueno is not None)
    cliente.close()


def test_dos_procesos_un_solo_lease_en_mongo(db):
    import multiprocessing

    db.sesiones.insert_one({
        "sid": "sid-procesos", "gen": 0, "revocada": False, "lease_hasta": None,
        "expira_en": "2099-01-01T00:00:00+00:00",
    })
    ctx = multiprocessing.get_context("spawn")
    cola = ctx.Queue()
    procesos = [ctx.Process(target=_reclamar_mongo, args=(cola,)) for _ in range(2)]
    for proceso in procesos:
        proceso.start()
    for proceso in procesos:
        proceso.join(20)
        assert proceso.exitcode == 0
    ganadores = [cola.get(timeout=5) for _ in range(2)]
    assert ganadores.count(True) == 1


def test_indices_parciales_dejan_pasar_legacy_y_rechazan_duplicados(db):
    db.usuario.insert_many([
        {"user": "sin-campos"},
        {"user": "nulos", "aegis_user_id": None, "aegis_tenant_id": None},
        {"user": "vacios", "aegis_user_id": "", "aegis_tenant_id": ""},
    ])
    db.solicitudes_acceso.insert_many([
        {"empresa": "A", "idempotencia": None},
        {"empresa": "B"},
        {"empresa": "C", "idempotencia": ""},
    ])
    assert aplicar_indices(db) == []
    db.usuario.insert_one({"user": "otro-legacy"})
    db.solicitudes_acceso.insert_one({"empresa": "D", "idempotencia": None})
    completo = {"aegis_user_id": str(uuid.uuid4()), "aegis_tenant_id": str(uuid.uuid4())}
    db.usuario.insert_one({"user": "vinculado", **completo})
    with pytest.raises(DuplicateKeyError) as error:
        db.usuario.insert_one({"user": "copia", **completo})
    assert error.value.code == 11000
    db.solicitudes_acceso.insert_one({"empresa": "E", "idempotencia": "clave-real"})
    with pytest.raises(DuplicateKeyError) as error_solicitud:
        db.solicitudes_acceso.insert_one({"empresa": "F", "idempotencia": "clave-real"})
    assert error_solicitud.value.code == 11000
    assert db.usuario.count_documents({}) == 5
    assert db.solicitudes_acceso.count_documents({"idempotencia": None}) == 3
    assert db.solicitudes_acceso.count_documents({"idempotencia": ""}) == 1


def test_auditoria_informa_duplicados_sin_borrarlos(db):
    pareja = {"aegis_user_id": "usuario-1", "aegis_tenant_id": "tenant-1"}
    db.usuario.insert_many([
        {"user": "uno", **pareja},
        {"user": "dos", **pareja},
    ])
    db.solicitudes_acceso.insert_many([
        {"idempotencia": "misma"},
        {"idempotencia": "misma"},
    ])
    conflictos = aplicar_indices(db)
    colecciones = {c["coleccion"] for c in conflictos}
    assert "usuario" in colecciones
    assert "solicitudes_acceso" in colecciones
    assert db.usuario.count_documents({}) == 2
    assert db.solicitudes_acceso.count_documents({}) == 2
    nombres = {idx["name"] for idx in db.usuario.list_indexes()}
    assert nombres == {"_id_"}
