# api/login/logic.py
from flask import jsonify
from werkzeug.security import check_password_hash
from flask_jwt_extended import create_access_token
import logging

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


def login(mongo, user, password):
    try:
        if not user or not password:
            return jsonify({"error": "Usuario y contraseña son requeridos"}), 400

        # Buscar usuario en MongoDB
        usuario = mongo.db.usuario.find_one({"user": user})

        if not usuario:
            logger.warning(f"Login fallido — usuario no encontrado: {user}")
            return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

        if not check_password_hash(usuario["password"], password):
            logger.warning(f"Login fallido — contraseña incorrecta: {user}")
            return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

        role        = usuario.get("role", "EMPLOYEE")
        empleado_id = str(usuario.get("empleado_id") or "")
        org_id      = usuario.get("org_id", "default")

        # Permisos y módulos — primero los personalizados guardados en DB,
        # si no existen, usar los defaults por rol
        permisos = usuario.get("permisos") or PERMISOS_DEFAULT.get(role, PERMISOS_DEFAULT["EMPLOYEE"])
        modulos  = usuario.get("modulos")  or DASHBOARD_MODULOS.get(role, DASHBOARD_MODULOS["EMPLOYEE"])

        # Generar JWT con identidad completa
        identity = {
            "user":        user,
            "role":        role,
            "empleado_id": empleado_id,
            "org_id":      org_id,
        }
        access_token = create_access_token(identity=identity)

        logger.info(f"Login exitoso: {user} ({role})")

        return jsonify({
            "access_token": access_token,
            "user":         user,
            "role":         role,
            "empleado_id":  empleado_id,
            "org_id":       org_id,
            "permisos":     permisos,
            "modulos":      modulos,
        }), 200

    except Exception as e:
        logger.error(f"Error en login: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500