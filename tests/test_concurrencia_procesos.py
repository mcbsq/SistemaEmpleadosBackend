# Lease entre dos procesos. No usa MONGO_URI ni la base del proyecto:
# el candado es una base SQLite desechable con transacción inmediata.
import multiprocessing
import os
import tempfile


def _reclamar(ruta, sid, gen, cola):
    import sys
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from core.sesiones import reclamar_lease
    from tests.soporte_sqlite import Envoltura
    mongo = Envoltura(ruta)
    _doc, dueno = reclamar_lease(mongo, sid, gen)
    cola.put(dueno is not None)


def test_dos_procesos_un_solo_lease():
    import sys
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from tests.soporte_sqlite import Envoltura

    fd, ruta = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    try:
        mongo = Envoltura(ruta)
        mongo.db.raw.sesiones.insert_one({
            "sid": "s1", "gen": 0, "revocada": False,
            "lease_hasta": None, "refresh_token": "r",
            "expira_en": "2099-01-01T00:00:00+00:00",
        })
        ctx = multiprocessing.get_context("spawn")
        cola = ctx.Queue()
        procesos = [
            ctx.Process(target=_reclamar, args=(ruta, "s1", 0, cola))
            for _ in range(2)
        ]
        for proceso in procesos:
            proceso.start()
        for proceso in procesos:
            proceso.join(20)
            assert proceso.exitcode == 0
        ganadores = [cola.get(timeout=5) for _ in range(2)]
        assert ganadores.count(True) == 1
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass
