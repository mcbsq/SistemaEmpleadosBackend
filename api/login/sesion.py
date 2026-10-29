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
# • Olvidé mi contraseña: este backend le pide a Aegis (Admin API) que
#   restablezca la contraseña; Aegis genera una TEMPORAL y nos la devuelve,
#   y aquí se envía al correo registrado de la persona. Al entrar con ella el
#   login obliga a definir una nueva (debe_cambiar_password, ver
#   api/login/logic.py). Si no hay forma de entregarla (sin correo o sin
#   SMTP) NO se toca la contraseña: se avisa al SUPER_ADMIN como antes.
#   La respuesta es siempre la misma exista o no la cuenta, para no revelar
#   quién está dado de alta.
# ─────────────────────────────────────────────────────────────────────────────
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import g, jsonify
from werkzeug.security import generate_password_hash

from core.public_rate_limit import RegistrationRateLimiter

logger = logging.getLogger(__name__)

_limite_recuperar = RegistrationRateLimiter(max_attempts=5, window_seconds=3600)
MENSAJE_RECUPERAR = ("Si la cuenta existe, te enviamos una contraseña temporal a tu correo registrado. "
                     "Entra con ella y el sistema te pedirá definir una nueva. Si tu cuenta no tiene "
                     "correo, avisamos al administrador de tu empresa.")
# Entre dos restablecimientos de la misma cuenta: evita que alguien que
# conoce tu correo te cambie la contraseña una y otra vez.
ESPERA_ENTRE_RESETS_MIN = 15


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
        hace = (datetime.now(timezone.utc) - timedelta(minutes=ESPERA_ENTRE_RESETS_MIN)).isoformat()
        if raw.recuperaciones.find_one({"user": u.get("user"), "org_id": org, "via": "aegis", "creado_en": {"$gte": hace}}):
            continue  # ya se envió una temporal hace poco
        g.org_id = org
        if restablecer_y_enviar(mongo, u, org):
            raw.recuperaciones.insert_one({
                "user": u.get("user"), "org_id": org, "ip": ip, "atendida": True, "via": "aegis",
                "creado_en": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("Contraseña temporal enviada por recuperación a %s (%s)", u.get("user"), org)
            continue

        pendiente = raw.recuperaciones.find_one({"user": u.get("user"), "org_id": org, "atendida": False})
        if pendiente:
            continue  # ya se avisó; no llenar de notificaciones
        raw.recuperaciones.insert_one({
            "user": u.get("user"), "org_id": org, "ip": ip, "atendida": False,
            "creado_en": datetime.now(timezone.utc).isoformat(),
        })
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


def restablecer_y_enviar(mongo, usuario, org_id):
    """
    Pide a Aegis una contraseña temporal para `usuario` y se la envía a su
    correo. Retorna True solo si la temporal quedó entregada. Nunca registra
    ni devuelve la contraseña.
    """
    from core.aegis_client import aegis_admin_reset_password
    from core.aegis_config import get_aegis_settings
    from core.mailer import build_tenant_login_url, mailer_enabled, send_temp_password_email

    destino = (usuario.get("email") or "").strip()
    if not destino or not mailer_enabled():
        return False  # sin forma de entregarla, no se cambia nada

    s = get_aegis_settings()
    if s["admin_enabled"] and usuario.get("aegis_user_id"):
        temp, err = aegis_admin_reset_password(str(usuario["aegis_user_id"]), tenant_id=org_id)
        if err or not temp:
            logger.warning("Aegis reset-password (recuperación) falló: %s", err[1] if err else "sin temporal")
            return False
    elif not s["login_enabled"]:
        # Modo legacy (sin Aegis): la temporal se genera y se guarda aquí.
        temp = secrets.token_urlsafe(10)
        mongo.db.raw.usuario.update_one({"_id": usuario["_id"]}, {"$set": {"password": generate_password_hash(temp)}})
    else:
        return False  # cuenta sin vínculo Aegis: la restablece su administrador

    # La bandera vive en Mongo para que sobreviva aunque se cierre la ventana
    # o se renueve la sesión: hasta cambiarla, el token solo sirve para eso.
    mongo.db.raw.usuario.update_one({"_id": usuario["_id"]}, {"$set": {"debe_cambiar_password": True}})
    enviado = send_temp_password_email(destino, usuario.get("user", ""), temp,
                                       login_url=build_tenant_login_url(org_id), restablecida=True)
    if not enviado:
        logger.error("Se restableció la contraseña de %s pero el correo no salió", usuario.get("user"))
    return enviado


def marcar_atendida(mongo, user, org_id):
    """Al restablecer la contraseña desde Cuentas, la solicitud queda atendida."""
    mongo.db.raw.recuperaciones.update_many(
        {"user": user, "org_id": org_id, "atendida": False},
        {"$set": {"atendida": True, "atendida_en": datetime.now(timezone.utc).isoformat()}},
    )
