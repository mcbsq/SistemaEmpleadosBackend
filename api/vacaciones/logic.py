# api/vacaciones/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Solicitud y aprobación de vacaciones. Los días disponibles se calculan sobre
# la tabla de antigüedad configurable en Configuración → Vacaciones (default:
# art. 76 LFT), menos los días ya aprobados en el año en curso.
# ─────────────────────────────────────────────────────────────────────────────
from datetime import datetime, date, timezone
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import jsonify
import logging

from api.org.logic import get_vacaciones_config
from core.mailer import send_generic_email, mailer_enabled
from api.notificaciones.logic import crear_notificacion

logger = logging.getLogger(__name__)


def _serialize(doc):
    doc["_id"] = str(doc["_id"])
    doc["empleado_id"] = str(doc["empleado_id"])
    return doc


def _antiguedad_anios(fecha_ingreso_str):
    """Años completos desde FechaIngreso (YYYY-MM-DD). None si no hay fecha."""
    if not fecha_ingreso_str:
        return None
    try:
        ingreso = datetime.strptime(fecha_ingreso_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    hoy = date.today()
    anios = hoy.year - ingreso.year - ((hoy.month, hoy.day) < (ingreso.month, ingreso.day))
    return max(anios, 0), ingreso


def _dias_por_antiguedad(anios, tabla):
    """Busca el escalón de la tabla <= anios (la tabla usa claves string)."""
    if anios is None or anios < 1:
        return 0
    escalones = sorted((int(k) for k in tabla.keys()), reverse=True)
    for e in escalones:
        if anios >= e:
            return tabla[str(e)]
    return 0


def calcular_balance(mongo, empleado_id, org_id="default"):
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400

    rh = mongo.db.rh.find_one({"empleado_id": eid}) or {}
    fecha_ingreso = rh.get("FechaIngreso")
    resultado = _antiguedad_anios(fecha_ingreso)

    if resultado is None:
        return jsonify({
            "antiguedad_anios": None,
            "fecha_ingreso": None,
            "dias_totales_anio": 0,
            "dias_usados_anio": 0,
            "dias_disponibles": 0,
            "es_aniversario_hoy": False,
            "proximo_aniversario": None,
            "mensaje": "Sin fecha de ingreso registrada — pide a RH que la complete.",
        }), 200

    anios, ingreso = resultado
    cfg = get_vacaciones_config(mongo, org_id)
    dias_totales = _dias_por_antiguedad(anios, cfg["tabla_dias_por_antiguedad"])

    hoy = date.today()
    inicio_anio_laboral = date(hoy.year if (hoy.month, hoy.day) >= (ingreso.month, ingreso.day) else hoy.year - 1,
                                ingreso.month, ingreso.day)

    usados = 0
    for sol in mongo.db.vacaciones_solicitudes.find({"empleado_id": eid, "estado": "aprobada"}):
        try:
            f_inicio = datetime.strptime(sol["fecha_inicio"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        if f_inicio >= inicio_anio_laboral:
            usados += sol.get("dias_solicitados", 0)

    es_aniversario_hoy = (hoy.month, hoy.day) == (ingreso.month, ingreso.day) and anios >= 1
    try:
        proximo = date(hoy.year, ingreso.month, ingreso.day)
        if proximo < hoy:
            proximo = date(hoy.year + 1, ingreso.month, ingreso.day)
    except ValueError:
        proximo = None  # 29 de febrero en año no bisiesto, caso raro

    return jsonify({
        "antiguedad_anios": anios,
        "fecha_ingreso": fecha_ingreso,
        "dias_totales_anio": dias_totales,
        "dias_usados_anio": usados,
        "dias_disponibles": max(dias_totales - usados, 0),
        "es_aniversario_hoy": es_aniversario_hoy,
        "proximo_aniversario": proximo.isoformat() if proximo else None,
    }), 200


def _dias_solicitados(fecha_inicio, fecha_fin):
    try:
        fi = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        ff = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
    except ValueError:
        return None
    if ff < fi:
        return None
    return (ff - fi).days + 1  # inclusivo; simplificación: no descuenta fines de semana


def crear_solicitud(mongo, empleado_id, data, creado_por_role):
    fecha_inicio = data.get("fecha_inicio")
    fecha_fin = data.get("fecha_fin")
    dias = _dias_solicitados(fecha_inicio, fecha_fin)
    if dias is None:
        return jsonify({"error": "fecha_inicio/fecha_fin inválidas"}), 400

    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400

    doc = {
        "empleado_id": eid,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "dias_solicitados": dias,
        "motivo": (data.get("motivo") or "").strip()[:300],
        "estado": "pendiente",
        "creado_por_role": creado_por_role,
        "creado_en": datetime.now(timezone.utc).isoformat(),
        "revisado_por": None,
        "revisado_en": None,
        "comentario_revision": "",
    }
    result = mongo.db.vacaciones_solicitudes.insert_one(doc)

    _notificar_nueva_solicitud(mongo, empleado_id, dias, fecha_inicio, fecha_fin)

    return jsonify({"_id": str(result.inserted_id), "dias_solicitados": dias, "message": "Solicitud enviada"}), 201


def _notificar_nueva_solicitud(mongo, empleado_id, dias, fecha_inicio, fecha_fin):
    cfg = get_vacaciones_config(mongo)
    try:
        emp = mongo.db.empleados.find_one({"_id": ObjectId(empleado_id)}) or {}
        nombre = f"{emp.get('Nombre','')} {emp.get('ApelPaterno','')}".strip() or "Un empleado"
        aprobadores = list(mongo.db.usuario.find({"role": {"$in": cfg["roles_aprueban"]}}))

        # Notificación dentro del sistema — siempre, independientemente del
        # correo (que es opcional y se controla aparte con notificar_por_correo).
        for aprobador in aprobadores:
            crear_notificacion(
                mongo, aprobador.get("user"), "vacaciones_solicitud",
                "Nueva solicitud de vacaciones",
                f"{nombre} solicitó vacaciones del {fecha_inicio} al {fecha_fin} ({dias} días).",
                link="/vacaciones",
            )

        if mailer_enabled() and cfg.get("notificar_por_correo", True):
            asunto = f"Nueva solicitud de vacaciones — {nombre}"
            cuerpo = (
                f"{nombre} solicitó vacaciones del {fecha_inicio} al {fecha_fin} ({dias} días).\n\n"
                f"Revísala en el sistema, sección Solicitudes de vacaciones."
            )
            for aprobador in aprobadores:
                email = aprobador.get("email")
                if email:
                    send_generic_email(email, asunto, cuerpo)
    except Exception as e:
        logger.error(f"No se pudo notificar solicitud de vacaciones: {e}")


def get_solicitudes_por_empleado(mongo, empleado_id):
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400
    docs = list(mongo.db.vacaciones_solicitudes.find({"empleado_id": eid}).sort("creado_en", -1))
    return jsonify([_serialize(d) for d in docs]), 200


def get_pendientes(mongo):
    docs = list(mongo.db.vacaciones_solicitudes.find({"estado": "pendiente"}).sort("creado_en", 1))
    empleados = {
        str(e["_id"]): f"{e.get('Nombre','')} {e.get('ApelPaterno','')}".strip()
        for e in mongo.db.empleados.find({}, {"Nombre": 1, "ApelPaterno": 1})
    }
    out = []
    for d in docs:
        s = _serialize(d)
        s["empleado_nombre"] = empleados.get(s["empleado_id"], "")
        out.append(s)
    return jsonify(out), 200


def actualizar_estado(mongo, solicitud_id, nuevo_estado, revisor_user, comentario=""):
    if nuevo_estado not in ("aprobada", "rechazada"):
        return jsonify({"error": "estado debe ser aprobada o rechazada"}), 400
    try:
        sid = ObjectId(solicitud_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "id inválido"}), 400

    sol = mongo.db.vacaciones_solicitudes.find_one({"_id": sid})
    if not sol:
        return jsonify({"error": "Solicitud no encontrada"}), 404
    if sol.get("estado") != "pendiente":
        return jsonify({"error": "Esta solicitud ya fue revisada"}), 400

    mongo.db.vacaciones_solicitudes.update_one(
        {"_id": sid},
        {"$set": {
            "estado": nuevo_estado,
            "revisado_por": revisor_user,
            "revisado_en": datetime.now(timezone.utc).isoformat(),
            "comentario_revision": (comentario or "")[:300],
        }},
    )

    try:
        usuario = mongo.db.usuario.find_one({"empleado_id": str(sol["empleado_id"])})
        estado_txt = "aprobada ✓" if nuevo_estado == "aprobada" else "rechazada"
        if usuario and usuario.get("user"):
            crear_notificacion(
                mongo, usuario["user"], "vacaciones_resolucion",
                f"Tu solicitud de vacaciones fue {estado_txt}",
                f"Del {sol['fecha_inicio']} al {sol['fecha_fin']} ({sol['dias_solicitados']} días): {estado_txt}."
                + (f" Comentario: {comentario}" if comentario else ""),
                link="/vacaciones",
            )
        if mailer_enabled() and usuario and usuario.get("email"):
            send_generic_email(
                usuario["email"],
                f"Tu solicitud de vacaciones fue {estado_txt}",
                f"Del {sol['fecha_inicio']} al {sol['fecha_fin']} ({sol['dias_solicitados']} días): {estado_txt}."
                + (f"\n\nComentario: {comentario}" if comentario else ""),
            )
    except Exception as e:
        logger.error(f"No se pudo notificar resolución de vacaciones: {e}")

    return jsonify({"message": f"Solicitud {nuevo_estado}"}), 200
