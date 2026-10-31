# api/login/recuperacion.py
# ─────────────────────────────────────────────────────────────────────────────
# "¿Olvidaste tu contraseña?" al estilo Google, en tres pasos:
#   1. POST /recuperar/codigo     {email}           → código de 6 dígitos al correo
#   2. POST /recuperar/verificar  {email, codigo}   → token de un solo uso + empresas
#   3. POST /recuperar/confirmar  {token, org_id, nueva}
#      Empleados le pide a Aegis restablecer la cuenta (Admin API); Aegis
#      responde con una contraseña temporal y aquí mismo se usa para fijar la
#      nueva que eligió la persona. La temporal nunca sale del servidor.
#
# Identidad = posesión del correo registrado. El código vence en
# CODIGO_MINUTOS, admite INTENTOS_MAX intentos y solo sirve una vez; los
# límites viven en Mongo (no en memoria) para que valgan entre procesos.
# Las respuestas del paso 1 son iguales exista o no la cuenta. Las empresas
# de un correo solo se muestran DESPUÉS de verificar el código.
# ─────────────────────────────────────────────────────────────────────────────
import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import g, jsonify

from core.aegis_client import aegis_admin_reset_password, aegis_change_password
from core.aegis_config import get_aegis_settings
from core.contrasena import contrasena_aceptable
from core.mailer import mailer_enabled, send_codigo_recuperacion
from core.perfiles_aegis import APP_KEY

logger = logging.getLogger(__name__)

CODIGO_MINUTOS = 10
TOKEN_MINUTOS = 15
INTENTOS_MAX = 5
ESPERA_REENVIO_SEG = 60
CODIGOS_POR_HORA = 5

_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MENSAJE_CODIGO = ("Si hay una cuenta con ese correo, te enviamos un código de 6 dígitos. "
                  "Revisa también tu carpeta de spam.")
ERROR_CODIGO = "El código no es correcto o ya venció. Pide uno nuevo."


def _ahora():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _huella(valor):
    """HMAC del código/token: en la base nunca queda el valor en claro."""
    clave = (os.environ.get("JWT_SECRET_KEY") or "recuperacion").encode()
    return hmac.new(clave, str(valor).encode(), hashlib.sha256).hexdigest()


def _correo(data):
    return " ".join(str(data.get("email") or data.get("identificador") or "").split()).lower()[:254]


def _cuentas(mongo, email):
    """Cuentas activas con ese correo, en cualquier empresa."""
    return [u for u in mongo.db.raw.usuario.find({"email": email}) if u.get("activo") is not False]


def _nombre_empresa(mongo, org_id):
    org = mongo.db.raw.organizacion.find_one({"org_id": org_id}) or {}
    tenant = mongo.db.raw.tenants.find_one({"org_id": org_id}) or {}
    return org.get("name") or tenant.get("nombre") or tenant.get("name") or org_id


def solicitar_codigo(mongo, data, ip):
    email = _correo(data)
    if not _CORREO.match(email):
        return jsonify({"error": "Escribe el correo completo de tu cuenta."}), 400
    if not mailer_enabled():
        logger.error("Recuperación de contraseña sin servicio de correo configurado (RESEND_API_KEY/SMTP_HOST)")
        return jsonify({"error": "La recuperación por correo no está disponible por ahora. Contacta a tu administrador."}), 503

    col = mongo.db.raw.recuperacion_codigos
    ahora = _ahora()
    recientes = list(col.find({"email": email, "creado_en": {"$gte": _iso(ahora - timedelta(hours=1))}}))
    if len(recientes) >= CODIGOS_POR_HORA or len(list(col.find({"ip": ip, "creado_en": {"$gte": _iso(ahora - timedelta(hours=1))}}))) >= 20:
        return jsonify({"error": "Pediste demasiados códigos. Espera un rato e intenta de nuevo."}), 429
    if any(r.get("creado_en", "") >= _iso(ahora - timedelta(seconds=ESPERA_REENVIO_SEG)) for r in recientes):
        return jsonify({"message": MENSAJE_CODIGO, "reenviar_en": ESPERA_REENVIO_SEG}), 200

    cuentas = _cuentas(mongo, email)
    org_link = re.sub(r"[^a-z0-9_-]", "", str(data.get("org_id") or "").lower())[:63]
    if org_link:
        cuentas = [u for u in cuentas if (u.get("org_id") or "cibercom") == org_link] or cuentas
    if not cuentas:
        # Misma respuesta que si existiera; se guarda el intento para el límite.
        col.insert_one({"email": email, "ip": ip, "creado_en": _iso(ahora), "usado": True, "sin_cuenta": True})
        return jsonify({"message": MENSAJE_CODIGO, "reenviar_en": ESPERA_REENVIO_SEG}), 200

    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    col.update_many({"email": email, "usado": False}, {"$set": {"usado": True}})
    col.insert_one({
        "email": email, "ip": ip, "codigo": _huella(codigo), "intentos": 0, "usado": False,
        "verificado": False, "orgs": sorted({u.get("org_id") or "cibercom" for u in cuentas}),
        "creado_en": _iso(ahora), "expira_en": _iso(ahora + timedelta(minutes=CODIGO_MINUTOS)),
    })
    if not send_codigo_recuperacion(email, codigo, CODIGO_MINUTOS):
        logger.error("No salió el código de recuperación para %s", email)
    else:
        logger.info("Código de recuperación enviado a %s", email)
    return jsonify({"message": MENSAJE_CODIGO, "reenviar_en": ESPERA_REENVIO_SEG}), 200


def verificar_codigo(mongo, data):
    email = _correo(data)
    codigo = re.sub(r"\D", "", str(data.get("codigo") or ""))
    col = mongo.db.raw.recuperacion_codigos
    doc = None
    for d in col.find({"email": email, "usado": False, "verificado": False}):
        doc = d if doc is None or d.get("creado_en", "") > doc.get("creado_en", "") else doc
    if not doc or doc.get("expira_en", "") < _iso(_ahora()) or len(codigo) != 6:
        return jsonify({"error": ERROR_CODIGO}), 400

    if not hmac.compare_digest(doc.get("codigo", ""), _huella(codigo)):
        intentos = doc.get("intentos", 0) + 1
        agotado = intentos >= INTENTOS_MAX
        col.update_one({"_id": doc["_id"]}, {"$set": {"intentos": intentos, "usado": agotado}})
        if agotado:
            return jsonify({"error": "Demasiados intentos con este código. Pide uno nuevo."}), 400
        quedan = INTENTOS_MAX - intentos
        return jsonify({"error": f"El código no es correcto. Te {'queda' if quedan == 1 else 'quedan'} {quedan} {'intento' if quedan == 1 else 'intentos'}."}), 400

    token = secrets.token_urlsafe(32)
    col.update_one({"_id": doc["_id"]}, {"$set": {
        "verificado": True, "token": _huella(token),
        "token_expira_en": _iso(_ahora() + timedelta(minutes=TOKEN_MINUTOS)),
    }})
    empresas = [{"org_id": o, "nombre": _nombre_empresa(mongo, o)} for o in doc.get("orgs", [])]
    return jsonify({"token": token, "empresas": empresas}), 200


def confirmar(mongo, data):
    token = str(data.get("token") or "")
    nueva = data.get("nueva") or ""
    col = mongo.db.raw.recuperacion_codigos
    doc = col.find_one({"token": _huella(token), "verificado": True, "usado": False}) if token else None
    if not doc or doc.get("token_expira_en", "") < _iso(_ahora()):
        return jsonify({"error": "La verificación venció. Empieza de nuevo y pide otro código."}), 400
    if not contrasena_aceptable(nueva):
        return jsonify({"error": "La contraseña debe tener entre 12 y 256 caracteres, con mayúscula, minúscula, número y símbolo."}), 400

    orgs = doc.get("orgs", [])
    org_id = str(data.get("org_id") or "") or (orgs[0] if len(orgs) == 1 else "")
    if org_id not in orgs:
        return jsonify({"error": "Elige la empresa de la cuenta."}), 400
    usuario = next((u for u in _cuentas(mongo, doc["email"]) if (u.get("org_id") or "cibercom") == org_id), None)
    if not usuario:
        return jsonify({"error": "Esa cuenta ya no está activa. Contacta a tu administrador."}), 409

    g.org_id = org_id
    s = get_aegis_settings()
    if s["login_enabled"]:
        if not (s["admin_enabled"] and usuario.get("aegis_user_id")):
            return jsonify({"error": "Tu cuenta no se puede restablecer desde aquí. Pide a tu administrador que la restablezca desde Cuentas."}), 409
        # 1) Aegis restablece y responde con una temporal…
        temp, err = aegis_admin_reset_password(str(usuario["aegis_user_id"]), tenant_id=org_id)
        if err or not temp:
            logger.warning("Aegis reset-password (recuperación) falló: %s", err[1] if err else "sin temporal")
            return jsonify({"error": "El servicio de autenticación no respondió. Intenta de nuevo en un momento."}), 502
        # 2) …que se usa en el acto para fijar la contraseña que eligió la persona.
        identificador = usuario.get("email") or usuario.get("user")
        err = aegis_change_password(identificador, temp, nueva, tenant_id=org_id, app_id=APP_KEY)
        if err:
            body, status = err
            logger.warning("Aegis change-password (recuperación) HTTP %s: %s", status, body)
            detalle = body.get("detail") if isinstance(body, dict) else None
            if status in (400, 422) and isinstance(detalle, str):
                return jsonify({"error": detalle}), 400
            return jsonify({"error": "No se pudo guardar la contraseña nueva. Intenta de nuevo."}), 502
    else:
        from werkzeug.security import generate_password_hash
        mongo.db.raw.usuario.update_one({"_id": usuario["_id"]}, {"$set": {"password": generate_password_hash(nueva)}})

    col.update_one({"_id": doc["_id"]}, {"$set": {"usado": True, "usado_en": _iso(_ahora()), "org_id": org_id}})
    # Contraseña nueva = se cierran todas las sesiones y celulares de la cuenta.
    from core.sesiones import revocar_usuario
    from api.dispositivos.logic import revocar_de_usuario
    revocar_usuario(mongo, usuario.get("user"), org_id)
    revocar_de_usuario(mongo, usuario.get("user"), org_id, "recuperación de contraseña")
    try:
        from core.audit import registrar_auditoria
        registrar_auditoria(mongo, usuario.get("user"), usuario.get("role"), "update", "usuario",
                            str(usuario["_id"]), detalle="Contraseña restablecida con código por correo")
    except Exception:
        logger.exception("No se pudo registrar la auditoría de la recuperación")
    logger.info("Contraseña restablecida por código para %s (%s)", usuario.get("user"), org_id)
    return jsonify({"message": "Listo. Ya puedes entrar con tu contraseña nueva.", "usuario": identificador_login(usuario)}), 200


def identificador_login(usuario):
    return usuario.get("email") or usuario.get("user") or ""
