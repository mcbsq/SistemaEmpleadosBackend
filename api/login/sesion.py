# api/login/sesion.py
# ─────────────────────────────────────────────────────────────────────────────
# Sesión deslizante y recuperación de contraseña (pruebas TST, oct 2026).
#
# • Renovar sesión: antes el JWT vivía `sessionMinutes` fijos aunque la
#   persona estuviera trabajando, y al vencer la sacaba a media captura (p. ej.
#   en el alta de empleado de 3 pasos). Ahora el cliente, mientras haya
#   actividad, cambia su token vigente por uno nuevo; `sessionMinutes` pasa a
#   ser tiempo de INACTIVIDAD. Solo se renueva un token válido y de una cuenta
#   que sigue activa.
# • Olvidé mi contraseña: Aegis no permite que la persona la restablezca sola,
#   así que la solicitud avisa a quien administra las cuentas de su empresa
#   (SUPER_ADMIN), que la restablece desde Cuentas. La respuesta es
#   siempre la misma exista o no la cuenta, para no revelar quién está dado
#   de alta.
# ─────────────────────────────────────────────────────────────────────────────
import logging
import re
from datetime import datetime, timezone

from flask import g, jsonify

from core.public_rate_limit import RegistrationRateLimiter

logger = logging.getLogger(__name__)

_limite_recuperar = RegistrationRateLimiter(max_attempts=5, window_seconds=3600)
MENSAJE_RECUPERAR = ("Si la cuenta existe, avisamos al administrador de tu empresa para que "
                     "restablezca tu contraseña. Te la harán llegar por correo o en persona.")


def _cuenta(mongo, user, org_id):
    """Cuenta por usuario dentro de su empresa (cuentas legacy sin org_id = Cibercom)."""
    for u in mongo.db.raw.usuario.find({"user": user}):
        if (u.get("org_id") or "cibercom") == org_id:
            return u
    return None


def renovar(mongo, claims, emitir_sesion):
    user, org_id = claims.get("user"), claims.get("org_id")
    usuario = _cuenta(mongo, user, org_id) if user and org_id else None
    if not usuario or usuario.get("activo") is False:
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    g.org_id = org_id
    return emitir_sesion(mongo, usuario, user, org_id=org_id)


def solicitar_recuperacion(mongo, data, ip):
    identificador = " ".join(str(data.get("identificador") or "").split()).lower()[:120]
    org_id = re.sub(r"[^a-z0-9_-]", "", str(data.get("org_id") or "").lower())[:63] or None
    if len(identificador) < 3:
        return jsonify({"error": "Escribe tu usuario o tu correo."}), 400
    if not _limite_recuperar.allow(f"{ip}:{identificador}") or not _limite_recuperar.allow(f"ip:{ip}"):
        return jsonify({"error": "Demasiadas solicitudes. Intenta más tarde."}), 429

    raw = mongo.db.raw
    filtro = {"$or": [{"email": identificador}, {"user": identificador}]}
    for u in raw.usuario.find(filtro):
        org = u.get("org_id") or "cibercom"
        if (org_id and org != org_id) or u.get("activo") is False:
            continue
        pendiente = raw.recuperaciones.find_one({"user": u.get("user"), "org_id": org, "atendida": False})
        if pendiente:
            continue  # ya se avisó; no llenar de notificaciones
        raw.recuperaciones.insert_one({
            "user": u.get("user"), "org_id": org, "ip": ip, "atendida": False,
            "creado_en": datetime.now(timezone.utc).isoformat(),
        })
        g.org_id = org
        from api.notificaciones.logic import crear_notificacion
        for admin in mongo.db.usuario.find({"role": "SUPER_ADMIN"}):
            if admin.get("activo") is False or admin.get("user") == u.get("user"):
                continue
            crear_notificacion(
                mongo, admin.get("user"), "recuperar_contrasena",
                "Solicitud de nueva contraseña",
                f"{u.get('user')} olvidó su contraseña. Restablécela desde Cuentas.",
                link="/cuentas",
            )
        logger.info("Solicitud de recuperación de contraseña para %s (%s)", u.get("user"), org)
    return jsonify({"message": MENSAJE_RECUPERAR}), 200


def marcar_atendida(mongo, user, org_id):
    """Al restablecer la contraseña desde Cuentas, la solicitud queda atendida."""
    mongo.db.raw.recuperaciones.update_many(
        {"user": user, "org_id": org_id, "atendida": False},
        {"$set": {"atendida": True, "atendida_en": datetime.now(timezone.utc).isoformat()}},
    )
