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
# • Olvidé mi contraseña: se pide a Aegis con el tenant de la liga conocida.
#   No se resuelve el correo para averiguar si la cuenta existe y no se avisa
#   al administrador local. La respuesta pública es la misma en ambos casos.
#   La persona elige la contraseña en /admin/recover de Aegis, no aquí.
# ─────────────────────────────────────────────────────────────────────────────
import logging
import re
from datetime import datetime, timezone

from flask import jsonify

from core.aegis_client import aegis_get_access, aegis_refresh
from core.aegis_config import get_aegis_settings
from core.perfiles_aegis import APP_KEY, clasificar_perfiles, misma_empresa_y_app
from core.public_rate_limit import RegistrationRateLimiter
from core.rol_efectivo import acotar
from core.sesiones import (
    acceso_en_cache, confirmar_par, fijar_rol, marcar_acceso, obtener,
    reclamar_lease, revocar, soltar_lease,
)
from api.org.logic import get_session_minutes

logger = logging.getLogger(__name__)

_limite_recuperar = RegistrationRateLimiter(max_attempts=5, window_seconds=3600)
MENSAJE_RECUPERAR = (
    "Si los datos corresponden a una cuenta habilitada para recuperar el acceso, "
    "recibirás un correo con instrucciones. Revisa también la carpeta de correo no deseado."
)
MENSAJE_SIN_LIGA = "Abre la página de tu empresa y solicita la recuperación desde ahí."
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _cuenta(mongo, user, org_id):
    """Cuenta por usuario dentro de su empresa (cuentas legacy sin org_id = Cibercom)."""
    for u in mongo.db.raw.usuario.find({"user": user}):
        if (u.get("org_id") or "cibercom") == org_id:
            return u
    return None


def _transitorio(status):
    return status == 429 or status >= 500


def _emitir_vigente(mongo, claims, emitir_sesion, sid):
    user, org_id = claims.get("user"), claims.get("org_id")
    usuario = _cuenta(mongo, user, org_id) if user and org_id else None
    if not usuario or usuario.get("activo") is False:
        revocar(mongo, sid)
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    from flask import g
    g.org_id = org_id
    return emitir_sesion(mongo, usuario, user, org_id=org_id, sid_existente=sid)


def _renovar_aegis(mongo, claims, emitir_sesion, sesion):
    """
    Lease en Mongo antes de Aegis. El par nuevo se guarda antes de /v1/access.
    401/403 explícitos revocan. 429, 5xx y red dejan la sesión y responden 503.
    El perdedor del lease adopta la generación ganadora y no revoca.
    """
    if sesion.get("must_change_password"):
        return jsonify({"error": "Debes cambiar la contraseña antes de continuar."}), 403
    sid = sesion["sid"]
    gen = sesion.get("gen", 0)
    _previo, dueno = reclamar_lease(mongo, sid, gen)
    if not dueno:
        cruda = mongo.db.raw.sesiones.find_one({"sid": sid})
        if not cruda or cruda.get("revocada"):
            return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
        if cruda.get("gen", 0) != gen:
            return _emitir_vigente(mongo, claims, emitir_sesion, sid)
        return jsonify({"error": "La sesión se está renovando. Intenta de nuevo."}), 503

    tokens, err = aegis_refresh(
        sesion.get("refresh_token") or "",
        tenant_id=sesion.get("org_id"),
        app_id=sesion.get("app_key") or APP_KEY,
    )
    if err:
        status = err[1]
        if _transitorio(status):
            soltar_lease(mongo, sid, dueno)
            return jsonify({"error": "El servicio de identidad no está disponible."}), 503
        revocar(mongo, sid)
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    if not tokens or not tokens.get("access_token") or not tokens.get("refresh_token"):
        soltar_lease(mongo, sid, dueno)
        return jsonify({"error": "El servicio de identidad no está disponible."}), 503

    minutos = get_session_minutes(mongo, sesion.get("org_id"))
    guardado, _expira = confirmar_par(
        mongo, sid, gen, dueno, tokens, minutos,
        must_change_password=bool(tokens.get("must_change_password")),
    )
    if not guardado:
        return jsonify({"error": "La sesión se está renovando. Intenta de nuevo."}), 503

    acceso, acceso_err = aegis_get_access(
        tokens.get("access_token"), tenant_id=sesion.get("org_id"), app_id=APP_KEY,
    )
    perfil = {
        "tenant_id": sesion.get("aegis_tenant_id"),
        "app_key": APP_KEY,
        "is_active": True,
    }
    if acceso_err:
        if _transitorio(acceso_err[1]):
            return jsonify({"error": "El servicio de identidad no está disponible."}), 503
        revocar(mongo, sid)
        return jsonify({"error": "El acceso a Empleados no está disponible para esta cuenta."}), 403
    if not misma_empresa_y_app(perfil, acceso, APP_KEY) or clasificar_perfiles(acceso.get("roles")) == "denegado":
        revocar(mongo, sid)
        return jsonify({"error": "El acceso a Empleados no está disponible para esta cuenta."}), 403
    vigente = obtener(mongo, sid) or sesion
    efectivo = acotar(vigente.get("rol_local") or (vigente.get("claims") or {}).get("role"), acceso.get("roles"))
    if efectivo is None:
        revocar(mongo, sid)
        return jsonify({"error": "El acceso a Empleados no está disponible para esta cuenta."}), 403
    if efectivo != vigente.get("rol_efectivo"):
        fijar_rol(mongo, vigente, efectivo)
    return _emitir_vigente(mongo, claims, emitir_sesion, sid)


def renovar(mongo, claims, emitir_sesion):
    user, org_id = claims.get("user"), claims.get("org_id")
    sesion = obtener(mongo, claims.get("sid")) if claims.get("sid") else None
    if get_aegis_settings()["login_enabled"]:
        if not sesion or not sesion.get("refresh_token"):
            return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
        return _renovar_aegis(mongo, claims, emitir_sesion, sesion)
    if claims.get("sid"):
        if not sesion:
            return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
        if sesion.get("refresh_token"):
            return _renovar_aegis(mongo, claims, emitir_sesion, sesion)
        if not acceso_en_cache(sesion):
            marcar_acceso(mongo, sesion["sid"])
    usuario = _cuenta(mongo, user, org_id) if user and org_id else None
    if not usuario or usuario.get("activo") is False:
        if sesion:
            revocar(mongo, sesion["sid"])
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    from flask import g
    g.org_id = org_id
    return emitir_sesion(mongo, usuario, user, org_id=org_id, sid_existente=sesion["sid"] if sesion else None)


def solicitar_recuperacion(mongo, data, ip):
    """
    Correo completo y tenant de la liga. No consulta Mongo para decidir el
    mensaje y no llama a resolve-tenant. Sin liga no se llama a Aegis y no
    se dice que salió un correo.
    """
    del mongo  # la existencia local no cambia la respuesta
    correo = " ".join(str(data.get("identificador") or data.get("email") or "").split()).lower()[:254]
    org_id = re.sub(r"[^a-z0-9_-]", "", str(data.get("org_id") or "").lower())[:63] or None
    if not _CORREO.match(correo):
        return jsonify({"error": "Escribe el correo completo de la cuenta."}), 400
    if not org_id:
        return jsonify({"error": MENSAJE_SIN_LIGA}), 400
    if not _limite_recuperar.allow(f"{ip}:{correo}") or not _limite_recuperar.allow(f"ip:{ip}"):
        return jsonify({"error": "Demasiadas solicitudes. Intenta más tarde."}), 429
    if get_aegis_settings()["login_enabled"]:
        from core.aegis_client import aegis_password_reset_request
        err = aegis_password_reset_request(correo, org_id)
        if err and err[1] >= 500:
            return jsonify({"error": "El servicio de recuperación no está disponible."}), 503
        if err and err[1] == 429:
            return jsonify({"error": "Demasiadas solicitudes. Intenta más tarde."}), 429
    logger.info("Solicitud de recuperación recibida")
    return jsonify({"message": MENSAJE_RECUPERAR}), 200


def marcar_atendida(mongo, user, org_id):
    """Al restablecer la contraseña desde Cuentas, la solicitud queda atendida."""
    mongo.db.raw.recuperaciones.update_many(
        {"user": user, "org_id": org_id, "atendida": False},
        {"$set": {"atendida": True, "atendida_en": datetime.now(timezone.utc).isoformat()}},
    )
