# api/login/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Login: modo Aegis (delegar credenciales + obtener perfil /me) o modo legacy
# (hash en Mongo). En modo puente, tras Aegis se emite el mismo JWT local que
# ya consume el resto de la API (permisos/rol siguen saliendo de Mongo).
# ─────────────────────────────────────────────────────────────────────────────
from flask import jsonify
from werkzeug.security import check_password_hash
from flask_jwt_extended import create_access_token
import logging

from core.aegis_config import get_aegis_settings
from core.aegis_client import aegis_password_login, aegis_get_me

logger = logging.getLogger(__name__)

# ─── Permisos por rol (espejo del frontend) ───────────────────────────────────
PERMISOS_DEFAULT = {
    "SUPER_ADMIN":     ["*"],
    "ADMIN":           ["ver_empleados","crud_empleados","ver_expediente","ver_rh",
                        "ver_proyectos","ver_organigrama","ver_habilidades",
                        "ver_dashboard","ver_carrusel"],
    "EMPLOYEE":        ["ver_organigrama","ver_carrusel","ver_perfil_propio"],
    "JEFE_AREA":       ["ver_empleados","ver_organigrama","ver_proyectos",
                        "ver_habilidades","solo_equipo_directo","ver_carrusel",
                        "ver_dashboard"],
    "CONTADOR":        ["ver_empleados","ver_rh","ver_organigrama","ver_dashboard","ver_carrusel"],
    "PROJECT_MANAGER": ["ver_empleados","ver_proyectos","ver_habilidades",
                        "ver_organigrama","ver_dashboard","ver_carrusel"],
    "MEDICO":          ["ver_empleados","ver_expediente","ver_organigrama",
                        "ver_dashboard","ver_carrusel"],
}

DASHBOARD_MODULOS = {
    "SUPER_ADMIN":     ["dashboard_admin","home_carousel","organigrama"],
    "ADMIN":           ["dashboard_admin","home_carousel","organigrama"],
    "EMPLOYEE":        ["home_carousel","organigrama"],
    "JEFE_AREA":       ["dashboard_jefe_area","home_carousel","organigrama"],
    "CONTADOR":        ["dashboard_contador","home_carousel","organigrama"],
    "PROJECT_MANAGER": ["dashboard_pm","home_carousel","organigrama"],
    "MEDICO":          ["dashboard_medico","home_carousel","organigrama"],
}


def _find_usuario_after_aegis(mongo, profile: dict):
    """
    Aegis ya validó la contraseña; aquí enlazamos con datos de negocio (rol, empleado_id).
    Orden: id de Aegis → email guardado en Mongo → user igual a parte local o email completo.
    """
    uid = profile.get("id")
    email_raw = (profile.get("email") or "").strip()
    email = email_raw.lower() if email_raw else ""

    if uid is not None:
        u = mongo.db.usuario.find_one({"aegis_user_id": uid})
        if u:
            return u
        u = mongo.db.usuario.find_one({"aegis_user_id": str(uid)})
        if u:
            return u

    if email:
        u = mongo.db.usuario.find_one({"email": email})
        if u:
            return u
        local = email.split("@", 1)[0]
        u = mongo.db.usuario.find_one({"user": local})
        if u:
            return u
        u = mongo.db.usuario.find_one({"user": email})
        if u:
            return u

    return None


def _issue_token_response(usuario: dict, login_label: str):
    """
    Emite el access_token de Flask-JWT con la misma forma de identity que antes,
    para no romper rutas que usan get_jwt_identity(). login_label solo ayuda si falta user en el doc.
    """
    user = usuario.get("user") or login_label
    role = usuario.get("role", "EMPLOYEE")
    empleado_id = str(usuario.get("empleado_id") or "")
    org_id = usuario.get("org_id", "default")

    permisos = usuario.get("permisos") or PERMISOS_DEFAULT.get(role, PERMISOS_DEFAULT["EMPLOYEE"])
    modulos = usuario.get("modulos") or DASHBOARD_MODULOS.get(role, DASHBOARD_MODULOS["EMPLOYEE"])

    identity = {
        "user":        user,
        "role":        role,
        "empleado_id": empleado_id,
        "org_id":      org_id,
    }
    access_token = create_access_token(identity=identity)

    logger.info("Login exitoso: %s (%s)", user, role)

    return jsonify({
        "access_token": access_token,
        "user":         user,
        "role":         role,
        "empleado_id":  empleado_id,
        "org_id":       org_id,
        "permisos":     permisos,
        "modulos":      modulos,
    }), 200


def _login_legacy(mongo, user, password):
    """Flujo anterior: usuario y hash almacenados solo en Mongo (sin llamar a Aegis)."""
    if not user or not password:
        return jsonify({"error": "Usuario y contraseña son requeridos"}), 400

    usuario = mongo.db.usuario.find_one({"user": user})
    if not usuario:
        logger.warning("Login fallido — usuario no encontrado: %s", user)
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    stored = usuario.get("password")
    if not stored or not check_password_hash(stored, password):
        logger.warning("Login fallido — contraseña incorrecta: %s", user)
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    return _issue_token_response(usuario, user)


def login(mongo, identifier, password):
    """
    Punto único de entrada del login HTTP.
    `identifier` = lo que Aegis espera (email completo o parte local); la ruta
    también acepta el campo JSON `user` por compatibilidad con el frontend.
    """
    try:
        if not identifier or not password:
            return jsonify({"error": "Usuario y contraseña son requeridos"}), 400

        settings = get_aegis_settings()

        if settings["login_enabled"]:
            # 1) Autenticar contra Aegis (contraseña vive allí).
            tokens, err = aegis_password_login(identifier, password)
            if err:
                body, status = err
                # Transición: opcionalmente reintentar con hash Mongo si Aegis falla.
                if settings["legacy_fallback"] and status in (401, 403, 422):
                    logger.info("Aegis rechazó credenciales; fallback legacy para identifier=%s", identifier[:3] + "...")
                    return _login_legacy(mongo, identifier.strip(), password)
                if status == 401 or status == 403:
                    return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
                if status == 503:
                    if settings["legacy_fallback"]:
                        return _login_legacy(mongo, identifier.strip(), password)
                    return jsonify(body), 503
                logger.warning("Aegis login HTTP %s: %s", status, body)
                return jsonify({"error": "No se pudo iniciar sesión"}), 502

            access_token = tokens.get("access_token")
            if not access_token:
                logger.error("Aegis login sin access_token en respuesta")
                return jsonify({"error": "Error interno del servidor"}), 502

            # 2) Saber email/id canónico en Aegis para buscar la fila en Mongo.
            profile, me_err = aegis_get_me(access_token)
            if me_err:
                body, status = me_err
                logger.error("Aegis /v1/me falló: %s %s", status, body)
                return jsonify({"error": "No se pudo validar la sesión"}), 502

            usuario = _find_usuario_after_aegis(mongo, profile)
            if not usuario:
                logger.warning(
                    "Login Aegis OK pero sin fila en Mongo (id=%s email=%s)",
                    profile.get("id"),
                    profile.get("email"),
                )
                return jsonify({
                    "error": "Usuario no registrado en el sistema de empleados. Contacte al administrador.",
                }), 403

            # 3) Respuesta idéntica a la histórica: JWT propio + permisos desde Mongo.
            return _issue_token_response(usuario, identifier.strip())

        return _login_legacy(mongo, identifier.strip(), password)

    except Exception as e:
        logger.error("Error en login: %s", e)
        return jsonify({"error": "Error interno del servidor"}), 500
