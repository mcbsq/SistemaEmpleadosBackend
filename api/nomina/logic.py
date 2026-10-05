# api/nomina/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Motor de nómina: ISR/IMSS/deducciones con parámetros que el ADMIN o CONTADOR
# pueden editar (no hardcodeados). El cálculo es una SIMPLIFICACIÓN de la
# tabla real del SAT/IMSS — suficiente para un cálculo de referencia interno,
# no para timbrado fiscal oficial. Cada empresa que use el sistema puede
# ajustar la tabla ISR y el % de IMSS a su convenio real.
from datetime import date, datetime, timezone
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import jsonify
import logging

from core.audit import registrar_auditoria

logger = logging.getLogger(__name__)

# Tabla ISR mensual simplificada (referencia pública SAT, 2024) — el
# SUPER_ADMIN/ADMIN/CONTADOR puede sustituirla por la vigente de su país/año.
ISR_TABLA_DEFAULT = [
    {"limite_inferior": 0.01,     "limite_superior": 746.04,    "cuota_fija": 0.00,    "porcentaje_excedente": 1.92},
    {"limite_inferior": 746.05,   "limite_superior": 6332.05,   "cuota_fija": 14.32,   "porcentaje_excedente": 6.40},
    {"limite_inferior": 6332.06,  "limite_superior": 11128.01,  "cuota_fija": 371.83,  "porcentaje_excedente": 10.88},
    {"limite_inferior": 11128.02, "limite_superior": 12935.82,  "cuota_fija": 893.63,  "porcentaje_excedente": 16.00},
    {"limite_inferior": 12935.83, "limite_superior": 15487.71,  "cuota_fija": 1182.88, "porcentaje_excedente": 17.92},
    {"limite_inferior": 15487.72, "limite_superior": 31236.49,  "cuota_fija": 1640.18, "porcentaje_excedente": 21.36},
    {"limite_inferior": 31236.50, "limite_superior": 49233.00,  "cuota_fija": 5004.12, "porcentaje_excedente": 23.52},
    {"limite_inferior": 49233.01, "limite_superior": 93993.90,  "cuota_fija": 9236.89, "porcentaje_excedente": 30.00},
    {"limite_inferior": 93993.91, "limite_superior": 125325.20, "cuota_fija": 22665.17,"porcentaje_excedente": 32.00},
    {"limite_inferior": 125325.21,"limite_superior": 375975.61, "cuota_fija": 32691.18,"porcentaje_excedente": 34.00},
    {"limite_inferior": 375975.62,"limite_superior": None,      "cuota_fija": 117912.32,"porcentaje_excedente": 35.00},
]

PARAMETROS_DEFAULT = {
    "isr_tabla": ISR_TABLA_DEFAULT,
    "imss_porcentaje": 2.375,   # cuota obrera aproximada sobre salario mensual
    "otras_deducciones": [],   # [{nombre, tipo: "porcentaje"|"monto_fijo", valor}]
    # Prestaciones (ver api/nomina/prestaciones.py)
    "dias_aguinaldo": 15,       # LFT art. 87: mínimo 15; la empresa puede dar más
    "uma_diaria": 113.14,       # UMA vigente (INEGI la publica cada enero): tope de exenciones
    "jornada_horas": 8,         # horas de la jornada diaria: base del salario por hora
    "horas_extra_habilitadas": True,
}


def get_parametros(mongo, org_id="default"):
    doc = mongo.db.nomina_parametros.find_one({"org_id": org_id})
    if not doc:
        return {**PARAMETROS_DEFAULT, "org_id": org_id}
    return {
        "org_id": org_id,
        "isr_tabla": doc.get("isr_tabla", ISR_TABLA_DEFAULT),
        "imss_porcentaje": doc.get("imss_porcentaje", 2.375),
        "otras_deducciones": doc.get("otras_deducciones", []),
        "dias_aguinaldo": doc.get("dias_aguinaldo", PARAMETROS_DEFAULT["dias_aguinaldo"]),
        "uma_diaria": doc.get("uma_diaria", PARAMETROS_DEFAULT["uma_diaria"]),
        "jornada_horas": doc.get("jornada_horas", PARAMETROS_DEFAULT["jornada_horas"]),
        "horas_extra_habilitadas": doc.get("horas_extra_habilitadas", PARAMETROS_DEFAULT["horas_extra_habilitadas"]),
        "actualizado_por": doc.get("actualizado_por"),
        "actualizado_en": doc.get("actualizado_en"),
    }


def get_parametros_route(mongo, org_id="default"):
    return jsonify(get_parametros(mongo, org_id)), 200


def guardar_parametros(mongo, org_id, data, identity):
    antes = get_parametros(mongo, org_id)

    isr_tabla = data.get("isr_tabla")
    if not isinstance(isr_tabla, list) or not isr_tabla:
        return jsonify({"error": "isr_tabla debe ser una lista de rangos"}), 400
    try:
        imss_porcentaje = float(data.get("imss_porcentaje"))
    except (TypeError, ValueError):
        return jsonify({"error": "imss_porcentaje inválido"}), 400
    otras_deducciones = data.get("otras_deducciones") or []
    if not isinstance(otras_deducciones, list):
        return jsonify({"error": "otras_deducciones debe ser una lista"}), 400
    try:
        dias_aguinaldo = float(data.get("dias_aguinaldo", antes["dias_aguinaldo"]))
        uma_diaria = float(data.get("uma_diaria", antes["uma_diaria"]))
        jornada_horas = float(data.get("jornada_horas", antes["jornada_horas"]))
    except (TypeError, ValueError):
        return jsonify({"error": "Días de aguinaldo, UMA y jornada deben ser números"}), 400
    if dias_aguinaldo < 15:
        return jsonify({"error": "La ley exige al menos 15 días de aguinaldo"}), 400
    if uma_diaria <= 0:
        return jsonify({"error": "La UMA diaria debe ser mayor a cero"}), 400
    if not 1 <= jornada_horas <= 8:
        return jsonify({"error": "La jornada diaria debe estar entre 1 y 8 horas"}), 400
    horas_extra_habilitadas = bool(data.get("horas_extra_habilitadas", antes["horas_extra_habilitadas"]))

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None

    doc = {
        "isr_tabla": isr_tabla,
        "imss_porcentaje": imss_porcentaje,
        "otras_deducciones": otras_deducciones,
        "dias_aguinaldo": dias_aguinaldo,
        "uma_diaria": uma_diaria,
        "jornada_horas": jornada_horas,
        "horas_extra_habilitadas": horas_extra_habilitadas,
        "actualizado_por": usuario,
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }
    mongo.db.nomina_parametros.update_one({"org_id": org_id}, {"$set": doc}, upsert=True)

    registrar_auditoria(
        mongo, usuario, role, "update", "nomina_parametros", org_id,
        cambios={
            "isr_tabla": {"antes": antes.get("isr_tabla"), "despues": isr_tabla},
            "imss_porcentaje": {"antes": antes.get("imss_porcentaje"), "despues": imss_porcentaje},
            "otras_deducciones": {"antes": antes.get("otras_deducciones"), "despues": otras_deducciones},
            "dias_aguinaldo": {"antes": antes.get("dias_aguinaldo"), "despues": dias_aguinaldo},
            "uma_diaria": {"antes": antes.get("uma_diaria"), "despues": uma_diaria},
            "jornada_horas": {"antes": antes.get("jornada_horas"), "despues": jornada_horas},
        },
    )

    return jsonify({"message": "Parámetros de nómina actualizados"}), 200


def _calcular_isr(sueldo_mensual, tabla):
    for rango in sorted(tabla, key=lambda r: r["limite_inferior"]):
        li = rango["limite_inferior"]
        ls = rango["limite_superior"]
        if sueldo_mensual >= li and (ls is None or sueldo_mensual <= ls):
            excedente = sueldo_mensual - li
            return round(rango["cuota_fija"] + excedente * rango["porcentaje_excedente"] / 100, 2)
    return 0.0


def _calcular_otras_deducciones(sueldo_mensual, deducciones):
    detalle = []
    total = 0.0
    for d in deducciones:
        nombre = d.get("nombre", "Deducción")
        if d.get("tipo") == "porcentaje":
            monto = round(sueldo_mensual * float(d.get("valor", 0)) / 100, 2)
        else:
            monto = round(float(d.get("valor", 0)), 2)
        detalle.append({"nombre": nombre, "monto": monto})
        total += monto
    return detalle, round(total, 2)


def calcular_nomina(mongo, empleado_id, periodo="mensual", org_id="default", mes=None):
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400

    rh = mongo.db.rh.find_one({"empleado_id": eid})
    if not rh:
        return jsonify({"error": "El empleado no tiene expediente de RH"}), 404
    if (rh.get("TipoRelacionLaboral") or "nomina") == "prestador_servicios":
        return jsonify({"error": "Un prestador de servicios no tiene cálculo de nómina (usa CFDI)"}), 400

    sueldo_mensual = float(rh.get("Salario") or 0)
    if sueldo_mensual <= 0:
        return jsonify({"error": "El empleado no tiene sueldo registrado en RH"}), 400

    params = get_parametros(mongo, org_id)
    isr = _calcular_isr(sueldo_mensual, params["isr_tabla"])
    imss = round(sueldo_mensual * params["imss_porcentaje"] / 100, 2)
    detalle_deducciones, total_otras = _calcular_otras_deducciones(sueldo_mensual, params["otras_deducciones"])

    # Horas extra aprobadas del mes (solo en el cálculo mensual): se suman a
    # la percepción y su parte gravada eleva la base del ISR.
    horas_extra = None
    if periodo == "mensual" and params.get("horas_extra_habilitadas", True):
        he = horas_extra_del_mes(mongo, rh, eid, mes, params)
        if he and he["totales"]["monto"] > 0:
            horas_extra = {"mes": he["mes"], **he["totales"]}
            isr = _calcular_isr(sueldo_mensual + he["totales"]["gravado"], params["isr_tabla"])

    total_deducciones = round(isr + imss + total_otras, 2)
    percepcion = sueldo_mensual + (horas_extra["monto"] if horas_extra else 0)
    neto_mensual = round(percepcion - total_deducciones, 2)

    factor = 0.5 if periodo == "quincenal" else 1
    resultado = {
        "empleado_id": empleado_id,
        "periodo": periodo,
        "sueldo": round(sueldo_mensual * factor, 2),
        "horas_extra": horas_extra,
        "percepcion_bruta": round(percepcion * factor, 2),
        "isr": round(isr * factor, 2),
        "imss": round(imss * factor, 2),
        "otras_deducciones": [{"nombre": d["nombre"], "monto": round(d["monto"] * factor, 2)} for d in detalle_deducciones],
        "total_deducciones": round(total_deducciones * factor, 2),
        "neto": round(neto_mensual * factor, 2),
        "calculado_en": datetime.now(timezone.utc).isoformat(),
    }
    return jsonify(resultado), 200


def calcular_nomina_dict(mongo, empleado_id, periodo="mensual", org_id="default"):
    """Versión no-Flask (regresa dict o None) para reutilizar el cálculo en otros módulos (reportes, etc.)."""
    try:
        eid = ObjectId(empleado_id)
        rh = mongo.db.rh.find_one({"empleado_id": eid})
        if not rh or (rh.get("TipoRelacionLaboral") or "nomina") == "prestador_servicios":
            return None
        sueldo_mensual = float(rh.get("Salario") or 0)
        if sueldo_mensual <= 0:
            return None
        params = get_parametros(mongo, org_id)
        isr = _calcular_isr(sueldo_mensual, params["isr_tabla"])
        imss = round(sueldo_mensual * params["imss_porcentaje"] / 100, 2)
        _, total_otras = _calcular_otras_deducciones(sueldo_mensual, params["otras_deducciones"])
        neto = round(sueldo_mensual - isr - imss - total_otras, 2)
        return {"percepcion_bruta": sueldo_mensual, "isr": isr, "imss": imss, "neto": neto}
    except Exception as e:
        logger.error(f"calcular_nomina_dict error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Aguinaldo y horas extra (cálculos en api/nomina/prestaciones.py)
# ─────────────────────────────────────────────────────────────────────────────
from api.nomina import prestaciones as P  # noqa: E402


def _isr_fn(params):
    return lambda base: _calcular_isr(base, params["isr_tabla"])


def _nombre(emp):
    return " ".join(x for x in [(emp or {}).get("Nombre"), (emp or {}).get("ApelPaterno"), (emp or {}).get("ApelMaterno")] if x).strip()


def _aguinaldo_de(rh, emp, anio, params):
    sd = P.salario_diario(rh)
    baja = P.parse_fecha(((emp or {}).get("baja") or {}).get("fecha"))
    calc = P.calcular_aguinaldo(
        sd, anio,
        fecha_ingreso=P.parse_fecha(rh.get("FechaIngreso")),
        fecha_baja=baja,
        dias_aguinaldo=float(params.get("dias_aguinaldo", 15)),
        uma_diaria=float(params.get("uma_diaria", 0)),
        isr_mensual=_isr_fn(params),
        sueldo_mensual=float(rh.get("Salario") or 0) or round(sd * P.DIAS_MES, 2),
    )
    calc["empleado_id"] = str(rh.get("empleado_id"))
    calc["nombre"] = _nombre(emp)
    calc["area"] = (emp or {}).get("depto_id") or "Sin asignar"
    calc["sin_fecha_ingreso"] = not P.parse_fecha(rh.get("FechaIngreso"))
    calc["dado_de_baja"] = bool(baja)
    return calc


def calcular_aguinaldo(mongo, empleado_id, anio, org_id="default"):
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400
    rh = mongo.db.rh.find_one({"empleado_id": eid})
    if not rh:
        return jsonify({"error": "El empleado no tiene expediente de RH"}), 404
    if (rh.get("TipoRelacionLaboral") or "nomina") == "prestador_servicios":
        return jsonify({"error": "Un prestador de servicios no recibe aguinaldo"}), 400
    if not P.salario_diario(rh):
        return jsonify({"error": "El empleado no tiene salario registrado en RH"}), 400
    emp = mongo.db.empleados.find_one({"_id": eid})
    return jsonify(_aguinaldo_de(rh, emp, anio, get_parametros(mongo, org_id))), 200


def reporte_aguinaldos(mongo, anio, org_id="default"):
    """Aguinaldo de toda la plantilla del año (incluye a quienes salieron ese año)."""
    params = get_parametros(mongo, org_id)
    empleados = {str(e["_id"]): e for e in mongo.db.empleados.find({"estado": {"$ne": "pendiente"}})}
    filas, sin_salario = [], []
    for rh in mongo.db.rh.find({}):
        eid = str(rh.get("empleado_id"))
        emp = empleados.get(eid)
        if not emp or (rh.get("TipoRelacionLaboral") or "nomina") == "prestador_servicios":
            continue
        baja = P.parse_fecha((emp.get("baja") or {}).get("fecha"))
        if baja and baja.year < anio:
            continue
        if not P.salario_diario(rh):
            sin_salario.append({"empleado_id": eid, "nombre": _nombre(emp)})
            continue
        filas.append(_aguinaldo_de(rh, emp, anio, params))
    filas.sort(key=lambda f: f["nombre"])
    total = lambda k: round(sum(f[k] for f in filas), 2)  # noqa: E731
    return jsonify({
        "anio": anio, "dias_aguinaldo": params.get("dias_aguinaldo"), "uma_diaria": params.get("uma_diaria"),
        "empleados": filas, "sin_salario": sin_salario,
        "totales": {"monto": total("monto"), "exento": total("exento"), "gravado": total("gravado"),
                    "isr": total("isr"), "neto": total("neto")},
    }), 200


def _rango_mes(mes):
    hoy = datetime.now(timezone.utc).date()
    try:
        y, m = (int(x) for x in str(mes).split("-")[:2]) if mes else (hoy.year, hoy.month)
        primero = date(y, m, 1)
    except (TypeError, ValueError):
        return None
    import calendar as _cal  # noqa: E402
    return primero, date(y, m, _cal.monthrange(y, m)[1])


def horas_extra_del_mes(mongo, rh, eid, mes, params):
    rango = _rango_mes(mes)
    if not rango:
        return None
    primero, ultimo = rango
    registros = [r for r in mongo.db.horas_extra.find({"empleado_id": str(eid), "estado": "aprobada"})
                 if (lambda f: f and primero <= f <= ultimo)(P.parse_fecha(r.get("fecha")))]
    calc = P.calcular_horas_extra(registros, P.salario_diario(rh), float(params.get("jornada_horas", 8)),
                                  float(params.get("uma_diaria", 0)))
    calc["mes"] = primero.strftime("%Y-%m")
    return calc


def _registro_publico(r, nombres):
    return {
        "_id": str(r["_id"]), "empleado_id": r.get("empleado_id"), "nombre": nombres.get(r.get("empleado_id"), ""),
        "fecha": r.get("fecha"), "horas": r.get("horas"), "motivo": r.get("motivo") or "",
        "estado": r.get("estado"), "registrado_por": r.get("registrado_por"), "registrado_en": r.get("registrado_en"),
        "resuelto_por": r.get("resuelto_por"), "comentario": r.get("comentario") or "",
    }


def listar_horas_extra(mongo, filtros, solo_empleados=None):
    q = {}
    if filtros.get("empleado_id"):
        q["empleado_id"] = filtros["empleado_id"]
    if filtros.get("estado"):
        q["estado"] = filtros["estado"]
    desde, hasta = P.parse_fecha(filtros.get("desde")), P.parse_fecha(filtros.get("hasta"))
    nombres = {str(e["_id"]): _nombre(e) for e in mongo.db.empleados.find({})}
    filas = []
    for r in mongo.db.horas_extra.find(q):
        if solo_empleados is not None and r.get("empleado_id") not in solo_empleados:
            continue
        f = P.parse_fecha(r.get("fecha"))
        if (desde and (not f or f < desde)) or (hasta and (not f or f > hasta)):
            continue
        filas.append(_registro_publico(r, nombres))
    filas.sort(key=lambda r: (r["fecha"] or "", r["registrado_en"] or ""), reverse=True)
    return filas


def registrar_horas_extra(mongo, data, identity, solo_empleados=None):
    params = get_parametros(mongo)
    if not params.get("horas_extra_habilitadas", True):
        return jsonify({"error": "Las horas extra están desactivadas en los parámetros de nómina"}), 400
    empleado_id = str(data.get("empleado_id") or "")
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "Selecciona un empleado"}), 400
    if solo_empleados is not None and empleado_id not in solo_empleados:
        return jsonify({"error": "Solo puedes registrar horas extra de tu equipo"}), 403
    emp = mongo.db.empleados.find_one({"_id": eid})
    if not emp or emp.get("estado") == "baja":
        return jsonify({"error": "El empleado no existe o ya fue dado de baja"}), 404
    fecha = P.parse_fecha(data.get("fecha"))
    if not fecha:
        return jsonify({"error": "Fecha inválida"}), 400
    if fecha > datetime.now(timezone.utc).date():
        return jsonify({"error": "No se pueden registrar horas extra de días futuros"}), 400
    try:
        horas = round(float(data.get("horas")), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Horas inválidas"}), 400
    if not 0 < horas <= 12:
        return jsonify({"error": "Las horas extra de un día deben ser entre 0 y 12"}), 400

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    # RH/administración registra ya aprobadas; un jefe propone y RH aprueba.
    estado = "pendiente" if role == "JEFE_AREA" else "aprobada"
    doc = {
        "empleado_id": empleado_id, "fecha": fecha.isoformat(), "horas": horas,
        "motivo": " ".join(str(data.get("motivo") or "").split())[:200],
        "estado": estado, "registrado_por": usuario,
        "registrado_en": datetime.now(timezone.utc).isoformat(),
        "resuelto_por": usuario if estado == "aprobada" else None,
    }
    ins = mongo.db.horas_extra.insert_one(doc)
    registrar_auditoria(mongo, usuario, role, "create", "horas_extra", str(ins.inserted_id),
                        detalle=f"{_nombre(emp)}: {horas:g} h el {fecha.isoformat()}")
    alertas = []
    if horas > P.MAX_HORAS_DOBLES_DIA:
        alertas.append(f"Rebasa el máximo legal de {P.MAX_HORAS_DOBLES_DIA} h diarias: el excedente se paga triple.")
    return jsonify({"_id": str(ins.inserted_id), "estado": estado, "alertas": alertas}), 201


def resolver_horas_extra(mongo, registro_id, data, identity):
    estado = data.get("estado")
    if estado not in ("aprobada", "rechazada"):
        return jsonify({"error": "estado debe ser aprobada o rechazada"}), 400
    try:
        oid = ObjectId(registro_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "Registro inválido"}), 400
    usuario = identity.get("user") if isinstance(identity, dict) else None
    r = mongo.db.horas_extra.update_one({"_id": oid}, {"$set": {
        "estado": estado, "resuelto_por": usuario, "resuelto_en": datetime.now(timezone.utc).isoformat(),
        "comentario": " ".join(str(data.get("comentario") or "").split())[:200],
    }})
    if not r.matched_count:
        return jsonify({"error": "Registro no encontrado"}), 404
    registrar_auditoria(mongo, usuario, identity.get("role") if isinstance(identity, dict) else None,
                        "update", "horas_extra", registro_id, detalle=estado)
    return jsonify({"message": "Actualizado", "estado": estado}), 200


def eliminar_horas_extra(mongo, registro_id, identity):
    try:
        oid = ObjectId(registro_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "Registro inválido"}), 400
    r = mongo.db.horas_extra.delete_one({"_id": oid})
    if not r.deleted_count:
        return jsonify({"error": "Registro no encontrado"}), 404
    registrar_auditoria(mongo, identity.get("user"), identity.get("role"), "delete", "horas_extra", registro_id)
    return jsonify({"message": "Eliminado"}), 200


def calcular_horas_extra_empleado(mongo, empleado_id, mes, org_id="default"):
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400
    rh = mongo.db.rh.find_one({"empleado_id": eid})
    if not rh or not P.salario_diario(rh):
        return jsonify({"error": "El empleado no tiene salario registrado en RH"}), 400
    calc = horas_extra_del_mes(mongo, rh, eid, mes, get_parametros(mongo, org_id))
    if calc is None:
        return jsonify({"error": "mes debe tener formato AAAA-MM"}), 400
    return jsonify(calc), 200
