# tests/test_prestaciones_bajas.py
# Aguinaldo (LFT art. 87), horas extra (LFT arts. 66–68), bajas y rotación.
from datetime import date

from bson.objectid import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.bajas.routes import setup_bajas_routes
from api.nomina import prestaciones as P
from api.nomina.routes import setup_nomina_routes
from tests.fakes import FakeMongo


# ── Cálculos puros ──────────────────────────────────────────────────────────
def test_aguinaldo_anio_completo_es_15_dias():
    r = P.calcular_aguinaldo(400.0, 2025, fecha_ingreso=date(2020, 3, 1))
    assert r["dias_trabajados"] == 365 and not r["proporcional"]
    assert r["dias_a_pagar"] == 15 and r["monto"] == 6000.0


def test_aguinaldo_proporcional_por_ingreso_y_por_baja():
    # Entra el 1 de julio de 2025 (año no bisiesto): 184 días → 15 × 184/365.
    r = P.calcular_aguinaldo(400.0, 2025, fecha_ingreso=date(2025, 7, 1))
    assert r["dias_trabajados"] == 184 and r["proporcional"]
    assert r["dias_a_pagar"] == round(15 * 184 / 365, 2)
    # Sale el 31 de marzo: 90 días.
    r = P.calcular_aguinaldo(400.0, 2025, fecha_ingreso=date(2019, 1, 1), fecha_baja=date(2025, 3, 31))
    assert r["dias_trabajados"] == 90


def test_aguinaldo_exento_hasta_30_umas_y_el_resto_gravado():
    isr = lambda base: base * 0.1  # noqa: E731 — ISR ficticio del 10 %
    r = P.calcular_aguinaldo(1000.0, 2025, dias_aguinaldo=30, uma_diaria=100.0, isr_mensual=isr, sueldo_mensual=30400)
    assert r["monto"] == 30000.0
    assert r["exento"] == 3000.0 and r["gravado"] == 27000.0
    assert r["isr"] == 2700.0 and r["neto"] == 27300.0


def test_horas_extra_dobles_y_triples_segun_lft():
    # Salario diario 800, jornada 8 h → 100 por hora.
    registros = [
        {"fecha": "2026-09-07", "horas": 2},   # lunes: 2 dobles
        {"fecha": "2026-09-08", "horas": 4},   # martes: 3 dobles + 1 triple (más de 3 h al día)
        {"fecha": "2026-09-09", "horas": 3},   # miércoles: 3 dobles (llega a 8 dobles)
        {"fecha": "2026-09-10", "horas": 2},   # jueves: cuarto día en la semana → triples
    ]
    r = P.calcular_horas_extra(registros, 800.0, 8, uma_diaria=100.0)
    s = r["semanas"][0]
    assert s["dobles"] == 8 and s["triples"] == 3
    assert s["pago_dobles"] == 1600.0 and s["pago_triples"] == 900.0
    # Exento: 50 % de las dobles (800) con tope de 5 UMA (500).
    assert s["exento"] == 500.0 and s["gravado"] == 2000.0
    assert len(s["alertas"]) >= 3


def test_horas_extra_respeta_tope_semanal_de_9_dobles():
    registros = [{"fecha": "2026-09-07", "horas": 3}, {"fecha": "2026-09-08", "horas": 3},
                 {"fecha": "2026-09-09", "horas": 3}]
    s = P.calcular_horas_extra(registros, 800.0, 8)["semanas"][0]
    assert s["dobles"] == 9 and s["triples"] == 0 and not s["alertas"]


def test_rotacion_mensual():
    personas = [
        {"area": "Almacén", "ingreso": date(2024, 1, 1), "baja": None},
        {"area": "Almacén", "ingreso": date(2024, 1, 1), "baja": date(2026, 2, 10), "tipo_baja": "renuncia"},
        {"area": "Ventas", "ingreso": date(2024, 1, 1), "baja": None},
        {"area": "Ventas", "ingreso": date(2026, 2, 15), "baja": None},
    ]
    r = P.calcular_rotacion(personas, date(2026, 2, 1), date(2026, 2, 28))
    feb = r["por_mes"][0]
    assert feb["plantilla_inicial"] == 3 and feb["plantilla_final"] == 3
    assert feb["altas"] == 1 and feb["bajas"] == 1 and feb["rotacion_pct"] == 33.3
    almacen = next(a for a in r["por_area"] if a["area"] == "Almacén")
    assert almacen["bajas"] == 1 and almacen["rotacion_pct"] == 50.0
    assert r["por_tipo"] == {"renuncia": 1}


# ── Rutas ───────────────────────────────────────────────────────────────────
def _app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-that-is-longer-than-thirty-two-bytes"
    JWTManager(app)
    mongo = FakeMongo()
    setup_bajas_routes(app, mongo)
    setup_nomina_routes(app, mongo)
    return app, mongo


def _h(app, role="RH", empleado_id="rh1"):
    with app.app_context():
        t = create_access_token(identity="ana", additional_claims={"user": "ana", "role": role, "org_id": "acme",
                                                                    "empleado_id": empleado_id})
    return {"Authorization": f"Bearer {t}"}


def _empleado(mongo, nombre="Luis", ingreso="2024-01-15", salario_diario=500):
    eid = ObjectId()
    mongo.db.empleados.insert_one({"_id": eid, "Nombre": nombre, "ApelPaterno": "Pérez", "depto_id": "Almacén", "estado": "activo"})
    mongo.db.rh.insert_one({"empleado_id": eid, "FechaIngreso": ingreso, "SalarioDiario": salario_diario,
                            "Salario": salario_diario * 30.4, "Puesto": "Encargado de almacén"})
    mongo.db.usuario.insert_one({"user": nombre.lower(), "role": "EMPLOYEE", "empleado_id": str(eid)})
    return eid


def test_baja_conserva_expediente_desactiva_cuenta_y_cuenta_en_rotacion():
    app, mongo = _app()
    c = app.test_client()
    eid = _empleado(mongo)

    r = c.post(f"/empleados/{eid}/baja", json={"fecha": "2026-09-30", "tipo": "renuncia", "motivo": "Mejor oferta"}, headers=_h(app))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["aguinaldo_proporcional"]["dias_trabajados"] == 273

    emp = mongo.db.empleados.find_one({"_id": eid})
    assert emp["estado"] == "baja" and emp["baja"]["tipo"] == "renuncia"
    assert mongo.db.rh.find_one({"empleado_id": eid})  # el expediente sigue ahí
    assert mongo.db.usuario.find_one({"user": "luis"})["activo"] is False

    # No se puede dar de baja dos veces.
    assert c.post(f"/empleados/{eid}/baja", json={"fecha": "2026-09-30", "tipo": "renuncia", "motivo": "x x x"}, headers=_h(app)).status_code == 409

    rot = c.get("/rotacion?desde=2026-09&hasta=2026-09", headers=_h(app)).get_json()
    assert rot["bajas"] == 1 and rot["bajas_detalle"][0]["tipo_label"] == "Renuncia voluntaria"


def test_baja_valida_datos_y_permisos():
    app, mongo = _app()
    c = app.test_client()
    eid = _empleado(mongo)
    r = c.post(f"/empleados/{eid}/baja", json={"fecha": "2023-01-01", "tipo": "x"}, headers=_h(app))
    assert r.status_code == 400 and set(r.get_json()["campos"]) == {"fecha", "tipo", "motivo"}
    assert c.post(f"/empleados/{eid}/baja", json={}, headers=_h(app, role="EMPLOYEE")).status_code == 403
    # Un empleado no ve la rotación salvo que se le otorgue el reporte.
    assert c.get("/rotacion", headers=_h(app, role="EMPLOYEE")).status_code == 403
    mongo.db.analitica_permisos.insert_one({"tipo": "config", "permisos": {"EMPLOYEE": ["rotacion"]}})
    assert c.get("/rotacion", headers=_h(app, role="EMPLOYEE")).status_code == 200


def test_reingreso_archiva_la_baja_y_reactiva_la_cuenta():
    app, mongo = _app()
    c = app.test_client()
    eid = _empleado(mongo)
    c.post(f"/empleados/{eid}/baja", json={"fecha": "2026-03-31", "tipo": "termino_contrato", "motivo": "Fin de temporada"}, headers=_h(app))
    assert c.post(f"/empleados/{eid}/reingreso", json={"fecha": "2026-03-01"}, headers=_h(app)).status_code == 400
    assert c.post(f"/empleados/{eid}/reingreso", json={"fecha": "2026-06-01"}, headers=_h(app)).status_code == 200

    emp = mongo.db.empleados.find_one({"_id": eid})
    assert emp["estado"] == "activo" and len(emp["historial_bajas"]) == 1
    assert mongo.db.rh.find_one({"empleado_id": eid})["FechaIngreso"] == "2026-06-01"
    assert mongo.db.usuario.find_one({"user": "luis"})["activo"] is True
    # La salida de marzo sigue contando en la rotación.
    rot = c.get("/rotacion?desde=2026-03&hasta=2026-06", headers=_h(app)).get_json()
    assert rot["bajas"] == 1 and rot["altas"] == 1


def test_horas_extra_registro_aprobacion_y_nomina_del_mes():
    app, mongo = _app()
    c = app.test_client()
    eid = _empleado(mongo, salario_diario=800)

    # Un jefe solo propone horas de su equipo; quedan pendientes.
    mongo.db.rh.update_one({"empleado_id": eid}, {"$set": {"JefeInmediato_id": "jefe1"}})
    r = c.post("/horas-extra", json={"empleado_id": str(eid), "fecha": "2026-09-08", "horas": 4, "motivo": "Pedido urgente"},
               headers=_h(app, role="JEFE_AREA", empleado_id="jefe1"))
    assert r.status_code == 201 and r.get_json()["estado"] == "pendiente" and r.get_json()["alertas"]
    otro = _empleado(mongo, nombre="Ana")
    assert c.post("/horas-extra", json={"empleado_id": str(otro), "fecha": "2026-09-08", "horas": 1},
                  headers=_h(app, role="JEFE_AREA", empleado_id="jefe1")).status_code == 403

    # Pendiente no se paga; al aprobarla entra a la nómina del mes.
    calc = c.get(f"/nomina/calcular/{eid}?mes=2026-09", headers=_h(app)).get_json()
    assert calc["horas_extra"] is None
    rid = r.get_json()["_id"]
    assert c.patch(f"/horas-extra/{rid}", json={"estado": "aprobada"}, headers=_h(app)).status_code == 200
    calc = c.get(f"/nomina/calcular/{eid}?mes=2026-09", headers=_h(app)).get_json()
    assert calc["horas_extra"]["dobles"] == 3 and calc["horas_extra"]["triples"] == 1
    assert calc["percepcion_bruta"] == round(800 * 30.4 + 3 * 100 * 2 + 1 * 100 * 3, 2)

    # Validaciones: días futuros y horas fuera de rango.
    assert c.post("/horas-extra", json={"empleado_id": str(eid), "fecha": "2099-01-01", "horas": 1}, headers=_h(app)).status_code == 400
    assert c.post("/horas-extra", json={"empleado_id": str(eid), "fecha": "2026-09-01", "horas": 20}, headers=_h(app)).status_code == 400


def test_parametros_de_aguinaldo_respetan_minimo_legal_y_reporte_anual():
    app, mongo = _app()
    c = app.test_client()
    _empleado(mongo, ingreso="2026-07-01", salario_diario=400)
    base = c.get("/nomina/parametros", headers=_h(app)).get_json()
    assert base["dias_aguinaldo"] == 15
    r = c.put("/nomina/parametros", json={**base, "dias_aguinaldo": 10}, headers=_h(app))
    assert r.status_code == 400
    assert c.put("/nomina/parametros", json={**base, "dias_aguinaldo": 20}, headers=_h(app)).status_code == 200
    rep = c.get("/nomina/aguinaldo?anio=2026", headers=_h(app)).get_json()
    fila = rep["empleados"][0]
    assert fila["dias_trabajados"] == 184 and fila["dias_a_pagar"] == round(20 * 184 / 365, 2)
