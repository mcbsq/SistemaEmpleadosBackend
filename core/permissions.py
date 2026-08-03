# core/permissions.py
# ─────────────────────────────────────────────────────────────────────────────
# Fuente única de verdad de permisos por rol. Antes cada ruta decidía acceso
# con una lista de NOMBRES de rol escrita a mano (@require_roles('ADMIN',
# 'CONTADOR', ...)) — un rol personalizado creado desde Gestión de roles
# (colección `roles_custom`) nunca podía pasar ningún filtro, sin importar qué
# permisos le hubiera marcado el SUPER_ADMIN en el asistente. Esto lo corrige:
# las rutas ahora piden un PERMISO (ver_empleados, ver_rh, ...) y este módulo
# resuelve ese permiso tanto para roles de sistema como para roles_custom.
#
# Vocabulario de permisos — debe coincidir exactamente con PERMISOS_DEF en
# Components/RoleManager.jsx (el catálogo que ve el SUPER_ADMIN al crear roles).
from functools import wraps
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt

# Permisos por rol de sistema (espejo de RoleManager.jsx / authService.js).
PERMISOS_DEFAULT = {
    "SUPER_ADMIN":     ["*"],
    "ADMIN":           ["ver_empleados", "crud_empleados", "ver_expediente", "ver_rh",
                        "ver_proyectos", "ver_organigrama", "ver_habilidades",
                        "ver_dashboard", "ver_carrusel", "gestionar_roles",
                        "monitor_incidencias", "ver_perfil_equipo"],
    "EMPLOYEE":        ["ver_organigrama", "ver_carrusel", "ver_perfil_propio"],
    "JEFE_AREA":       ["ver_empleados", "ver_organigrama", "ver_proyectos",
                        "ver_habilidades", "solo_equipo_directo", "ver_carrusel",
                        "ver_dashboard"],
    "CONTADOR":        ["ver_empleados", "ver_rh", "ver_organigrama", "ver_dashboard", "ver_carrusel"],
    "PROJECT_MANAGER": ["ver_empleados", "ver_proyectos", "ver_habilidades",
                        "ver_organigrama", "ver_dashboard", "ver_carrusel"],
    "MEDICO":          ["ver_empleados", "ver_expediente", "ver_organigrama",
                        "ver_dashboard", "ver_carrusel"],
}

DASHBOARD_MODULOS = {
    "SUPER_ADMIN":     ["dashboard_admin", "home_carousel", "organigrama"],
    "ADMIN":           ["dashboard_admin", "home_carousel", "organigrama"],
    "EMPLOYEE":        ["home_carousel", "organigrama"],
    "JEFE_AREA":       ["dashboard_jefe_area", "home_carousel", "organigrama"],
    "CONTADOR":        ["dashboard_contador", "home_carousel", "organigrama"],
    "PROJECT_MANAGER": ["dashboard_pm", "home_carousel", "organigrama"],
    "MEDICO":          ["dashboard_medico", "home_carousel", "organigrama"],
}

_ROLES_SISTEMA = set(PERMISOS_DEFAULT.keys())


def get_permisos_for_role(mongo, role):
    """
    Resuelve los permisos de CUALQUIER rol — de sistema o personalizado.
    SUPER_ADMIN siempre tiene "*" (todo). Los roles personalizados se leen de
    `roles_custom` (el mismo documento que edita RoleManager.jsx); si el rol
    no existe en ningún lado, se le niega todo (lista vacía) por seguridad.
    """
    if not role:
        return []
    if role in PERMISOS_DEFAULT:
        return PERMISOS_DEFAULT[role]

    try:
        doc = mongo.db.roles_custom.find_one({"tipo": "custom"})
        roles = doc.get("roles", []) if doc else []
        for r in roles:
            if r.get("nombre") == role:
                return r.get("permisos", [])
    except Exception:
        pass
    return []


def tiene_permiso(mongo, role, permiso):
    permisos = get_permisos_for_role(mongo, role)
    return "*" in permisos or permiso in permisos


def require_roles_or_permission(mongo, permiso, *roles_sistema):
    """
    Uso: @require_roles_or_permission(mongo, 'ver_empleados', 'EMPLOYEE', 'ADMIN', ...)
    Puente entre el esquema viejo (require_roles con lista fija) y el nuevo
    (permisos). Deja pasar exactamente a los mismos roles de sistema que antes
    (cero regresión) y ADEMÁS deja pasar a cualquier rol personalizado que
    tenga `permiso` marcado en Gestión de roles — que es lo que antes era
    imposible sin importar qué permisos tuviera el rol personalizado.
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt()
            role = identity.get("role") if isinstance(identity, dict) else None
            if role in roles_sistema:
                return f(*args, **kwargs)
            if role not in _ROLES_SISTEMA:
                permisos = get_permisos_for_role(mongo, role)
                if "*" in permisos or permiso in permisos:
                    return f(*args, **kwargs)
            return jsonify({"error": "Acceso no autorizado"}), 403
        return wrapper
    return decorator


def require_permission(mongo, *permisos_validos):
    """
    Uso: @require_permission(mongo, 'ver_empleados')
    A diferencia de require_roles (que compara nombres de rol hardcodeados),
    esto resuelve el rol del caller —de sistema o personalizado— contra su
    lista real de permisos. Un rol personalizado con "ver_empleados" marcado
    en el asistente de Gestión de roles ahora sí pasa este filtro.
    ADMIN y SUPER_ADMIN siempre pasan (son superusuarios del sistema).
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt()
            role = identity.get("role") if isinstance(identity, dict) else None
            if role in ("ADMIN", "SUPER_ADMIN"):
                return f(*args, **kwargs)
            permisos = get_permisos_for_role(mongo, role)
            if "*" in permisos or any(p in permisos for p in permisos_validos):
                return f(*args, **kwargs)
            return jsonify({"error": "Acceso no autorizado"}), 403
        return wrapper
    return decorator
