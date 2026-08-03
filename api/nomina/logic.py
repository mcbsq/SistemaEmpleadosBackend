# api/nomina/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Motor de nómina: ISR/IMSS/deducciones con parámetros que el ADMIN o CONTADOR
# pueden editar (no hardcodeados). El cálculo es una SIMPLIFICACIÓN de la
# tabla real del SAT/IMSS — suficiente para un cálculo de referencia interno,
# no para timbrado fiscal oficial. Cada empresa que use el sistema puede
# ajustar la tabla ISR y el % de IMSS a su convenio real.
from datetime import datetime, timezone
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

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None

    doc = {
        "org_id": org_id,
        "isr_tabla": isr_tabla,
        "imss_porcentaje": imss_porcentaje,
        "otras_deducciones": otras_deducciones,
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


def calcular_nomina(mongo, empleado_id, periodo="mensual", org_id="default"):
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

    total_deducciones = round(isr + imss + total_otras, 2)
    neto_mensual = round(sueldo_mensual - total_deducciones, 2)

    factor = 0.5 if periodo == "quincenal" else 1
    resultado = {
        "empleado_id": empleado_id,
        "periodo": periodo,
        "percepcion_bruta": round(sueldo_mensual * factor, 2),
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
