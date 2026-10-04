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


ROLES_APROBACION_FINAL = ("ADMIN", "SUPER_ADMIN", "RH")


def _ahora():
    return datetime.now(timezone.utc).isoformat()


def _jefe_de(mongo, empleado_id):
    """empleado_id (str) del jefe directo según la ficha laboral, o None."""
    try:
        doc = mongo.db.rh.find_one({"empleado_id": ObjectId(str(empleado_id))}, {"JefeInmediato_id": 1}) or {}
    except (InvalidId, TypeError):
        return None
    jefe = doc.get("JefeInmediato_id")
    jefe = str(jefe) if jefe else None
    return jefe if jefe and jefe != str(empleado_id) else None


def _aprobaciones(sol):
    """Doble visto bueno (oct 2026): jefe directo + RH/Administración.
    Las solicitudes viejas no traen el bloque: se tratan como de una sola
    etapa (la de RH), para no dejarlas atoradas esperando a un jefe."""
    ap = sol.get("aprobaciones")
    if ap:
        return ap
    return {"jefe": {"estado": "no_aplica"}, "rh": {"estado": "pendiente"}}


def _etapas_que_puede_resolver(sol, role, empleado_id_revisor):
    ap = _aprobaciones(sol)
    etapas = []
    if ap["jefe"].get("estado") == "pendiente" and empleado_id_revisor \
            and str(ap["jefe"].get("jefe_empleado_id")) == str(empleado_id_revisor):
        etapas.append("jefe")
    if ap["rh"].get("estado") == "pendiente" and role in ROLES_APROBACION_FINAL:
        etapas.append("rh")
    return etapas


def _nombre_empleado(mongo, empleado_id):
    try:
        emp = mongo.db.empleados.find_one({"_id": ObjectId(str(empleado_id))}, {"Nombre": 1, "ApelPaterno": 1}) or {}
    except (InvalidId, TypeError):
        emp = {}
    return f"{emp.get('Nombre','')} {emp.get('ApelPaterno','')}".strip()


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
    cfg = get_vacaciones_config(mongo)
    jefe = _jefe_de(mongo, empleado_id) if cfg.get("doble_aprobacion", True) else None
    doc["aprobaciones"] = {
        "jefe": {"estado": "pendiente", "jefe_empleado_id": jefe, "jefe_nombre": _nombre_empleado(mongo, jefe)}
                if jefe else {"estado": "no_aplica"},
        "rh": {"estado": "pendiente"},
    }
    result = mongo.db.vacaciones_solicitudes.insert_one(doc)

    _notificar_nueva_solicitud(mongo, empleado_id, dias, fecha_inicio, fecha_fin, jefe)

    return jsonify({"_id": str(result.inserted_id), "dias_solicitados": dias, "message": "Solicitud enviada"}), 201


def _aprobadores_finales(mongo):
    return list(mongo.db.usuario.find({"role": {"$in": list(ROLES_APROBACION_FINAL)}}))


def _avisar(mongo, usuarios, titulo, texto, cfg):
    for u in usuarios:
        if u and u.get("user"):
            crear_notificacion(mongo, u["user"], "vacaciones_solicitud", titulo, texto, link="/vacaciones")
    if mailer_enabled() and cfg.get("notificar_por_correo", True):
        for u in usuarios:
            if u and u.get("email"):
                send_generic_email(u["email"], titulo, texto + "\n\nRevísala en el sistema, sección Solicitudes de vacaciones.")


def _notificar_nueva_solicitud(mongo, empleado_id, dias, fecha_inicio, fecha_fin, jefe_empleado_id=None):
    """Avisa al jefe directo (primer visto bueno) y a RH/Administración
    (aprobación final). Las dos etapas pueden resolverse en cualquier orden;
    la solicitud queda aprobada solo cuando ambas dieron su visto bueno."""
    cfg = get_vacaciones_config(mongo)
    try:
        nombre = _nombre_empleado(mongo, empleado_id) or "Un empleado"
        texto = f"{nombre} solicitó vacaciones del {fecha_inicio} al {fecha_fin} ({dias} días)."
        destinatarios = _aprobadores_finales(mongo)
        if jefe_empleado_id:
            jefe_user = mongo.db.usuario.find_one({"empleado_id": str(jefe_empleado_id)})
            if jefe_user and all(jefe_user.get("user") != d.get("user") for d in destinatarios):
                destinatarios.append(jefe_user)
        _avisar(mongo, destinatarios, "Nueva solicitud de vacaciones", texto, cfg)
    except Exception as e:
        logger.error(f"No se pudo notificar solicitud de vacaciones: {e}")


def get_solicitudes_por_empleado(mongo, empleado_id):
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400
    docs = list(mongo.db.vacaciones_solicitudes.find({"empleado_id": eid}).sort("creado_en", -1))
    return jsonify([_serialize(d) for d in docs]), 200


def get_pendientes(mongo, role=None, empleado_id_revisor=None):
    """RH/Administración ven toda la cola; cualquier otra persona ve solo las
    solicitudes de su equipo directo que esperan su visto bueno de jefe."""
    docs = list(mongo.db.vacaciones_solicitudes.find({"estado": "pendiente"}).sort("creado_en", 1))
    es_rh = role in ROLES_APROBACION_FINAL
    empleados = {
        str(e["_id"]): f"{e.get('Nombre','')} {e.get('ApelPaterno','')}".strip()
        for e in mongo.db.empleados.find({}, {"Nombre": 1, "ApelPaterno": 1})
    }
    out = []
    for d in docs:
        etapas = _etapas_que_puede_resolver(d, role, empleado_id_revisor)
        if not es_rh and "jefe" not in etapas:
            continue
        d["aprobaciones"] = _aprobaciones(d)
        s = _serialize(d)
        s["empleado_nombre"] = empleados.get(s["empleado_id"], "")
        s["puedo_resolver"] = etapas
        out.append(s)
    return jsonify(out), 200


def actualizar_estado(mongo, solicitud_id, nuevo_estado, revisor_user, comentario="",
                      role=None, empleado_id_revisor=None):
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

    etapas = _etapas_que_puede_resolver(sol, role, empleado_id_revisor)
    if not etapas:
        return jsonify({"error": "Esta solicitud no espera tu visto bueno"}), 403

    ahora = _ahora()
    comentario = (comentario or "")[:300]
    ap = _aprobaciones(sol)
    for etapa in etapas:
        ap[etapa] = {**ap[etapa], "estado": nuevo_estado, "por": revisor_user, "en": ahora, "comentario": comentario}

    completas = all(ap[e].get("estado") in ("aprobada", "no_aplica") for e in ("jefe", "rh"))
    estado_final = "rechazada" if nuevo_estado == "rechazada" else ("aprobada" if completas else "pendiente")

    cambios = {"aprobaciones": ap, "estado": estado_final}
    if estado_final != "pendiente":
        cambios.update({"revisado_por": revisor_user, "revisado_en": ahora, "comentario_revision": comentario})
    mongo.db.vacaciones_solicitudes.update_one({"_id": sid}, {"$set": cambios})

    try:
        usuario = mongo.db.usuario.find_one({"empleado_id": str(sol["empleado_id"])})
        periodo = f"Del {sol['fecha_inicio']} al {sol['fecha_fin']} ({sol['dias_solicitados']} días)"
        if estado_final == "pendiente":
            falta = "RH" if ap["rh"].get("estado") == "pendiente" else "tu jefe directo"
            titulo = "Tu solicitud de vacaciones va avanzando"
            texto = f"{periodo}: ya tiene un visto bueno. Falta el de {falta}."
        else:
            titulo = f"Tu solicitud de vacaciones fue {estado_final}"
            texto = f"{periodo}: {estado_final}." + (f" Comentario: {comentario}" if comentario else "")
        if usuario and usuario.get("user"):
            crear_notificacion(mongo, usuario["user"], "vacaciones_resolucion", titulo, texto, link="/vacaciones")
        if estado_final != "pendiente" and mailer_enabled() and usuario and usuario.get("email"):
            send_generic_email(usuario["email"], titulo, texto)
    except Exception as e:
        logger.error(f"No se pudo notificar resolución de vacaciones: {e}")

    mensajes = {
        "aprobada": "Solicitud aprobada",
        "rechazada": "Solicitud rechazada",
        "pendiente": "Visto bueno registrado; falta la otra aprobación",
    }
    return jsonify({"message": mensajes[estado_final], "estado": estado_final, "aprobaciones": ap}), 200
