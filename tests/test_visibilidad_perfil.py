# tests/test_visibilidad_perfil.py
# Matriz de quién ve qué en el perfil (observaciones de RH, oct 2026): un
# compañero no debe ver sueldo, horario ni vacaciones de otro; el jefe
# directo sí ve horario y vacaciones (no sueldo); el empleado ve lo suyo con
# bancarios enmascarados.
from bson.objectid import ObjectId

from core.visibilidad_perfil import acceso_perfil, filtrar_rh
from core.validadores_mx import validar_curp, validar_rfc, validar_nss, validar_clabe
from tests.fakes import FakeMongo


def _setup():
    mongo = FakeMongo()
    jefe, emp, otro = ObjectId(), ObjectId(), ObjectId()
    mongo.db.rh.insert_one({"empleado_id": emp, "JefeInmediato_id": str(jefe)})
    return mongo, str(jefe), str(emp), str(otro)


def test_companero_solo_ve_tarjeta_publica_y_profesional():
    mongo, _, emp, otro = _setup()
    a = acceso_perfil(mongo, {"role": "EMPLOYEE", "empleado_id": otro}, emp)
    vistos = {k for k, v in a["ver"].items() if v}
    assert vistos == {"publico", "profesional"}
    assert not any(a["editar"].values())


def test_jefe_directo_ve_horario_y_vacaciones_pero_no_sueldo():
    mongo, jefe, emp, _ = _setup()
    a = acceso_perfil(mongo, {"role": "JEFE_AREA", "empleado_id": jefe}, emp)
    assert a["ver"]["laboral"] and a["ver"]["vacaciones"] and a["ver"]["emergencia"]
    assert not a["ver"]["compensacion"] and not a["ver"]["contacto"]


def test_propio_no_edita_laboral_ni_compensacion():
    mongo, _, emp, _ = _setup()
    a = acceso_perfil(mongo, {"role": "EMPLOYEE", "empleado_id": emp}, emp)
    assert all(a["ver"].values())
    assert not a["editar"]["laboral"] and not a["editar"]["compensacion"]
    assert a["editar"]["contacto"] and a["editar"]["profesional"]


def test_rh_ve_y_edita_todo():
    mongo, _, emp, _ = _setup()
    a = acceso_perfil(mongo, {"role": "ADMIN", "empleado_id": None}, emp)
    assert all(a["ver"].values()) and all(a["editar"].values())


def test_filtrar_rh_recorta_salario_al_jefe_y_enmascara_banco_al_propio():
    mongo, jefe, emp, _ = _setup()
    base = {"Puesto": "Dev", "SalarioDiario": 500, "Salario": 15200, "CLABE": "002010077777777771"}
    al_jefe = filtrar_rh(mongo, {"role": "JEFE_AREA", "empleado_id": jefe}, emp, dict(base))
    assert "SalarioDiario" not in al_jefe and "CLABE" not in al_jefe and al_jefe["Puesto"] == "Dev"
    al_propio = filtrar_rh(mongo, {"role": "EMPLOYEE", "empleado_id": emp}, emp, dict(base))
    assert al_propio["SalarioDiario"] == 500 and al_propio["CLABE"].endswith("7771")
    assert al_propio["CLABE"].startswith("•")
    al_contador = filtrar_rh(mongo, {"role": "CONTADOR", "empleado_id": None}, emp, dict(base))
    assert al_contador["CLABE"] == base["CLABE"]


def test_validadores_mx():
    assert validar_curp("HEGG560427MVZRRL04") is None
    assert validar_curp("HEGG560427MVZRRL05")
    assert validar_clabe("002010077777777771") is None
    assert validar_clabe("002010077777777772")
    assert validar_rfc("GODE561231GR8") is None and validar_rfc("XYZ")
    assert validar_nss("12345678903") is None and validar_nss("12345678901")
    assert validar_curp("") is None  # vacío = opcional


def test_coherencia_curp_rfc_con_la_persona():
    from core.validadores_mx import coherencia_identidad
    ok = dict(curp="HEGG560427MVZRRL04", rfc="HEGG560427AB1", nombre="Gabriela", ap_paterno="Hernández",
              ap_materno="García", fecha_nac="1956-04-27")
    assert coherencia_identidad(**ok) == {}
    assert "CURP" in coherencia_identidad(**{**ok, "ap_paterno": "López"})
    assert "CURP" in coherencia_identidad(**{**ok, "fecha_nac": "1990-01-01"})
    assert "RFC" in coherencia_identidad(**{**ok, "rfc": "XAXX010101AB1"})
    # Nombres compuestos comunes: "María Gabriela" usa la G.
    assert coherencia_identidad(**{**ok, "nombre": "María Gabriela"}) == {}
