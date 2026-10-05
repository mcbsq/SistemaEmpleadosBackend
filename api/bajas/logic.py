# api/bajas/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Bajas y rotación de personal (oct 2026).
#
# Antes la única salida era "Eliminar empleado", que borraba el expediente:
# sin historial no hay forma de medir rotación. Ahora la salida normal es DAR
# DE BAJA: el empleado queda con estado "baja" y los datos de su salida
# (fecha, tipo, motivo, si es recontratable); deja de aparecer en el
# directorio, el organigrama y los KPIs, y su cuenta se desactiva — pero su
# expediente se conserva para la rotación, el aguinaldo proporcional y un
# posible reingreso. Un reingreso archiva la baja en `historial_bajas`, así
# que cada periodo trabajado sigue contando en la rotación.
# ─────────────────────────────────────────────────────────────────────────────
import logging
from datetime import date, datetime, timezone

from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import g, jsonify

from api.nomina import prestaciones as P
from core.audit import registrar_auditoria

logger = logging.getLogger(__name__)

TIPOS_BAJA = {
    "renuncia": "Renuncia voluntaria",
    "despido": "Despido",
    "termino_contrato": "Término de contrato",
    "abandono": "Abandono de empleo",
    "jubilacion": "Jubilación",
    "otro": "Otro",
}


def _nombre(emp):
    return " ".join(x for x in [emp.get("Nombre"), emp.get("ApelPaterno"), emp.get("ApelMaterno")] if x).strip()


def _hoy():
    return datetime.now(timezone.utc).date()


def _rh_de(mongo, eid):
    return mongo.db.rh.find_one({"empleado_id": eid}) or {}


def _cuentas_de(mongo, empleado_id):
    return list(mongo.db.usuario.find({"empleado_id": {"$in": [empleado_id, _oid(empleado_id)]}}))


def _oid(valor):
    try:
        return ObjectId(valor)
    except (InvalidId, TypeError):
        return None


def _desactivar_cuentas(mongo, empleado_id, motivo):
    """La persona que sale ya no entra al sistema: cuenta inactiva, celulares
    desvinculados y su identidad en Aegis desactivada (mejor esfuerzo)."""
    from api.dispositivos.logic import revocar_de_usuario
    for u in _cuentas_de(mongo, empleado_id):
        mongo.db.usuario.update_one({"_id": u["_id"]}, {"$set": {"activo": False}})
        revocar_de_usuario(mongo, u.get("user"), getattr(g, "org_id", None) or u.get("org_id"), motivo)
        if u.get("aegis_user_id"):
            try:
                from core.aegis_client import aegis_admin_set_active
                err = aegis_admin_set_active(str(u["aegis_user_id"]), False, tenant_id=getattr(g, "org_id", None))
                if err:
                    logger.warning("No se pudo desactivar en Aegis a %s: %s", u.get("user"), err)
            except Exception as e:  # Aegis caído no debe impedir la baja
                logger.warning("Aegis no disponible al dar de baja a %s: %s", u.get("user"), e)


def _reactivar_cuentas(mongo, empleado_id):
    for u in _cuentas_de(mongo, empleado_id):
        mongo.db.usuario.update_one({"_id": u["_id"]}, {"$set": {"activo": True}})
        if u.get("aegis_user_id"):
            try:
                from core.aegis_client import aegis_admin_set_active
                aegis_admin_set_active(str(u["aegis_user_id"]), True, tenant_id=getattr(g, "org_id", None))
            except Exception as e:
                logger.warning("Aegis no disponible al reactivar a %s: %s", u.get("user"), e)


def dar_baja(mongo, empleado_id, data, identity):
    eid = _oid(empleado_id)
    if not eid:
        return jsonify({"error": "Empleado inválido"}), 400
    emp = mongo.db.empleados.find_one({"_id": eid})
    if not emp:
        return jsonify({"error": "Empleado no encontrado"}), 404
    if emp.get("estado") == "baja":
        return jsonify({"error": "Este empleado ya está dado de baja"}), 409
    if identity.get("empleado_id") and str(identity.get("empleado_id")) == empleado_id:
        return jsonify({"error": "No puedes darte de baja a ti mismo"}), 400

    errores = {}
    fecha = P.parse_fecha(data.get("fecha"))
    rh = _rh_de(mongo, eid)
    ingreso = P.parse_fecha(rh.get("FechaIngreso"))
    if not fecha:
        errores["fecha"] = "Indica la fecha de baja."
    elif fecha > _hoy():
        errores["fecha"] = "La fecha de baja no puede ser futura."
    elif ingreso and fecha < ingreso:
        errores["fecha"] = "La fecha de baja no puede ser anterior a su ingreso."
    tipo = data.get("tipo")
    if tipo not in TIPOS_BAJA:
        errores["tipo"] = "Elige el tipo de baja."
    motivo = " ".join(str(data.get("motivo") or "").split())[:500]
    if len(motivo) < 3:
        errores["motivo"] = "Describe brevemente el motivo."
    if errores:
        return jsonify({"error": "Revisa los datos de la baja", "campos": errores}), 400

    baja = {
        "fecha": fecha.isoformat(), "tipo": tipo, "motivo": motivo,
        "recontratable": bool(data.get("recontratable", True)),
        "ingreso": ingreso.isoformat() if ingreso else None,
        "area": emp.get("depto_id"), "puesto": rh.get("Puesto"),
        "registrado_por": identity.get("user"), "registrado_en": datetime.now(timezone.utc).isoformat(),
    }
    mongo.db.empleados.update_one({"_id": eid}, {"$set": {
        "estado": "baja", "estado_anterior": emp.get("estado") or "activo", "baja": baja,
    }})
    _desactivar_cuentas(mongo, empleado_id, "baja del empleado")
    registrar_auditoria(mongo, identity.get("user"), identity.get("role"), "baja", "empleados", empleado_id,
                        detalle=f"{_nombre(emp)} — {TIPOS_BAJA[tipo]} el {fecha.isoformat()}: {motivo}")

    # Referencia para el finiquito: aguinaldo proporcional del año de salida.
    aguinaldo = None
    sd = P.salario_diario(rh)
    if sd and (rh.get("TipoRelacionLaboral") or "nomina") != "prestador_servicios":
        from api.nomina.logic import get_parametros, _isr_fn
        params = get_parametros(mongo)
        aguinaldo = P.calcular_aguinaldo(
            sd, fecha.year, fecha_ingreso=ingreso, fecha_baja=fecha,
            dias_aguinaldo=float(params.get("dias_aguinaldo", 15)), uma_diaria=float(params.get("uma_diaria", 0)),
            isr_mensual=_isr_fn(params), sueldo_mensual=float(rh.get("Salario") or 0) or round(sd * P.DIAS_MES, 2))
    return jsonify({"message": "Empleado dado de baja", "baja": baja, "aguinaldo_proporcional": aguinaldo}), 200


def reingresar(mongo, empleado_id, data, identity):
    eid = _oid(empleado_id)
    if not eid:
        return jsonify({"error": "Empleado inválido"}), 400
    emp = mongo.db.empleados.find_one({"_id": eid})
    if not emp:
        return jsonify({"error": "Empleado no encontrado"}), 404
    if emp.get("estado") != "baja":
        return jsonify({"error": "Este empleado no está dado de baja"}), 409
    baja = emp.get("baja") or {}
    fecha = P.parse_fecha(data.get("fecha")) or _hoy()
    salida = P.parse_fecha(baja.get("fecha"))
    if salida and fecha <= salida:
        return jsonify({"error": "La fecha de reingreso debe ser posterior a la baja", "campos": {"fecha": "Debe ser posterior a la baja."}}), 400

    historial = list(emp.get("historial_bajas") or []) + [baja]
    mongo.db.empleados.update_one({"_id": eid}, {"$set": {
        "estado": emp.get("estado_anterior") if emp.get("estado_anterior") not in (None, "baja") else "activo",
        "baja": None, "historial_bajas": historial,
    }})
    # El nuevo periodo empieza en la fecha de reingreso (la antigüedad anterior
    # queda en historial_bajas[].ingreso).
    mongo.db.rh.update_one({"empleado_id": eid}, {"$set": {"FechaIngreso": fecha.isoformat()}})
    _reactivar_cuentas(mongo, empleado_id)
    registrar_auditoria(mongo, identity.get("user"), identity.get("role"), "reingreso", "empleados", empleado_id,
                        detalle=f"{_nombre(emp)} reingresa el {fecha.isoformat()}"
                                + ("" if baja.get("recontratable", True) else " (marcado como no recontratable)"))
    return jsonify({"message": "Empleado reingresado", "fecha": fecha.isoformat()}), 200


def _antiguedad_anios(ingreso, salida):
    if not ingreso or not salida:
        return None
    return round((salida - ingreso).days / 365.25, 1)


def listar_bajas(mongo, desde=None, hasta=None):
    """Cada salida (la vigente y las archivadas por reingreso), más reciente primero."""
    filas = []
    for emp in mongo.db.empleados.find({}):
        salidas = list(emp.get("historial_bajas") or [])
        if emp.get("estado") == "baja" and emp.get("baja"):
            salidas.append({**emp["baja"], "vigente": True})
        for b in salidas:
            f = P.parse_fecha(b.get("fecha"))
            if not f or (desde and f < desde) or (hasta and f > hasta):
                continue
            ingreso = P.parse_fecha(b.get("ingreso"))
            filas.append({
                "empleado_id": str(emp["_id"]), "nombre": _nombre(emp),
                "area": b.get("area") or emp.get("depto_id") or "Sin asignar", "puesto": b.get("puesto") or "",
                "ingreso": b.get("ingreso"), "fecha": b.get("fecha"),
                "antiguedad_anios": _antiguedad_anios(ingreso, f),
                "tipo": b.get("tipo"), "tipo_label": TIPOS_BAJA.get(b.get("tipo"), "Otro"),
                "motivo": b.get("motivo") or "", "recontratable": b.get("recontratable", True),
                "vigente": bool(b.get("vigente")),
            })
    filas.sort(key=lambda r: r["fecha"], reverse=True)
    return filas


def personas_para_rotacion(mongo):
    """Un renglón por periodo trabajado: el actual y los archivados."""
    administrativos = {str(u.get("empleado_id")) for u in mongo.db.usuario.find(
        {"role": {"$in": ["SUPER_ADMIN"]}}, {"empleado_id": 1}) if u.get("empleado_id")}
    rh = {str(d.get("empleado_id")): d for d in mongo.db.rh.find({}, {"empleado_id": 1, "FechaIngreso": 1})}
    personas = []
    for emp in mongo.db.empleados.find({}):
        eid = str(emp["_id"])
        if emp.get("estado") == "pendiente" or eid in administrativos:
            continue
        area = emp.get("depto_id") or "Sin asignar"
        for b in emp.get("historial_bajas") or []:
            personas.append({"area": b.get("area") or area, "ingreso": P.parse_fecha(b.get("ingreso")),
                             "baja": P.parse_fecha(b.get("fecha")), "tipo_baja": b.get("tipo")})
        baja = emp.get("baja") if emp.get("estado") == "baja" else None
        personas.append({
            "area": (baja or {}).get("area") or area,
            "ingreso": P.parse_fecha((rh.get(eid) or {}).get("FechaIngreso")),
            "baja": P.parse_fecha((baja or {}).get("fecha")), "tipo_baja": (baja or {}).get("tipo"),
        })
    return personas


def _mes(valor, fin=False):
    import calendar
    try:
        y, m = (int(x) for x in str(valor).split("-")[:2])
        return date(y, m, calendar.monthrange(y, m)[1] if fin else 1)
    except (TypeError, ValueError):
        return None


def rango_por_defecto():
    """Últimos 12 meses, incluido el actual."""
    hoy = _hoy()
    y, m = (hoy.year - 1, hoy.month + 1) if hoy.month < 12 else (hoy.year, 1)
    return date(y, m, 1), hoy


def rotacion(mongo, desde=None, hasta=None):
    d0, h0 = rango_por_defecto()
    desde = _mes(desde) if desde else d0
    hasta = _mes(hasta, fin=True) if hasta else h0
    if not desde or not hasta or desde > hasta:
        return None
    hasta = min(hasta, _hoy())
    datos = P.calcular_rotacion(personas_para_rotacion(mongo), desde, hasta)
    datos["por_tipo"] = [{"tipo": t, "label": TIPOS_BAJA.get(t, "Otro"), "total": n}
                         for t, n in sorted(datos["por_tipo"].items(), key=lambda x: -x[1])]
    datos["bajas_detalle"] = listar_bajas(mongo, desde, hasta)
    return datos
