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

# Qué ve un rol de los COMPAÑEROS (perfil público y directorio). Un empleado
# general ve cómo contactar a alguien y si está disponible — no su vida
# personal. Ver core/visibilidad_perfil.py::tarjeta_directorio.
PERMISOS_DIRECTORIO = [
    "dir_contacto",      # correo laboral, teléfono de oficina, extensión
    "dir_estado",        # activo, de vacaciones (y hasta cuándo), baja
    "dir_puesto",        # puesto, área y jefe inmediato
    "dir_profesional",   # descripción, educación, experiencia, habilidades
    "dir_cumpleanos",    # día y mes de cumpleaños (nunca el año)
]
# Celular y correo personal: solo si la empresa lo decide para un rol.
PERMISO_CONTACTO_PERSONAL = "dir_contacto_personal"

# Permisos por rol de sistema (espejo de RoleManager.jsx / authService.js).
PERMISOS_DEFAULT = {
    "SUPER_ADMIN":     ["*"],
    "ADMIN":           ["ver_empleados", "crud_empleados", "ver_expediente", "ver_rh",
                        "ver_proyectos", "ver_organigrama", "ver_habilidades",
                        "ver_dashboard", "ver_carrusel", "gestionar_roles",
                        "monitor_incidencias", "ver_perfil_equipo",
                        *PERMISOS_DIRECTORIO, PERMISO_CONTACTO_PERSONAL],
    "EMPLOYEE":        ["ver_organigrama", "ver_carrusel", "ver_perfil_propio",
                        *PERMISOS_DIRECTORIO],
    "JEFE_AREA":       ["ver_empleados", "ver_organigrama", "ver_proyectos",
                        "ver_habilidades", "solo_equipo_directo", "ver_carrusel",
                        "ver_dashboard", *PERMISOS_DIRECTORIO],
    "CONTADOR":        ["ver_empleados", "ver_rh", "ver_organigrama", "ver_dashboard", "ver_carrusel",
                        *PERMISOS_DIRECTORIO],
    "PROJECT_MANAGER": ["ver_empleados", "ver_proyectos", "ver_habilidades",
                        "ver_organigrama", "ver_dashboard", "ver_carrusel",
                        *PERMISOS_DIRECTORIO],
    "MEDICO":          ["ver_empleados", "ver_expediente", "ver_organigrama",
                        "ver_dashboard", "ver_carrusel", *PERMISOS_DIRECTORIO],
    # Recursos Humanos: todo lo de personas, nada de sistema.
    "RH":              ["ver_empleados", "crud_empleados", "ver_expediente", "ver_rh",
                        "ver_proyectos", "ver_organigrama", "ver_habilidades",
                        "ver_dashboard", "ver_carrusel", "ver_perfil_equipo",
                        *PERMISOS_DIRECTORIO, PERMISO_CONTACTO_PERSONAL],
}

DASHBOARD_MODULOS = {
    "SUPER_ADMIN":     ["dashboard_admin", "home_carousel", "organigrama"],
    "ADMIN":           ["dashboard_admin", "home_carousel", "organigrama"],
    "EMPLOYEE":        ["home_carousel", "organigrama"],
    "JEFE_AREA":       ["dashboard_jefe_area", "home_carousel", "organigrama"],
    "CONTADOR":        ["dashboard_contador", "home_carousel", "organigrama"],
    "PROJECT_MANAGER": ["dashboard_pm", "home_carousel", "organigrama"],
    "MEDICO":          ["dashboard_medico", "home_carousel", "organigrama"],
    "RH":              ["dashboard_rh", "home_carousel", "organigrama"],
}

_ROLES_SISTEMA = set(PERMISOS_DEFAULT.keys())


def config_roles(mongo):
    """
    Documento de roles de la empresa (colección `roles_custom`, uno por
    tenant): roles creados desde Gestión de roles, roles de sistema que la
    empresa eliminó y permisos editados de los roles de sistema.
    """
    try:
        doc = mongo.db.roles_custom.find_one({"tipo": "custom"}) or {}
    except Exception:
        doc = {}
    return {
        "custom":             [r for r in (doc.get("roles") or []) if isinstance(r, dict)],
        "sistema_eliminados": list(doc.get("sistema_eliminados") or []),
        "permisos_sistema":   dict(doc.get("permisos_sistema") or {}),
    }


def rol_existe(mongo, role):
    """Un rol se puede asignar si es de sistema (no eliminado) o personalizado."""
    if role == "SUPER_ADMIN":
        return True
    cfg = config_roles(mongo)
    if any(r.get("nombre") == role for r in cfg["custom"]):
        return True
    return role in PERMISOS_DEFAULT and role not in cfg["sistema_eliminados"]


def get_permisos_for_role(mongo, role):
    """
    Resuelve los permisos de CUALQUIER rol — de sistema o personalizado.
    SUPER_ADMIN siempre tiene "*" (todo). Orden:
      1. rol personalizado con ese nombre (incluye uno recreado "de cero" con
         el nombre de un rol de sistema que la empresa eliminó),
      2. rol de sistema con los permisos que la empresa le editó,
      3. permisos de fábrica del rol de sistema.
    Un rol que no existe en ningún lado (o de sistema eliminado) no tiene
    permisos, por seguridad.
    """
    if not role:
        return []
    if role == "SUPER_ADMIN":
        return ["*"]
    cfg = config_roles(mongo)
    for r in cfg["custom"]:
        if r.get("nombre") == role:
            return list(r.get("permisos") or [])
    if role in PERMISOS_DEFAULT:
        if role in cfg["sistema_eliminados"]:
            return []
        editados = cfg["permisos_sistema"].get(role)
        return list(editados) if isinstance(editados, list) else list(PERMISOS_DEFAULT[role])
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
            if role in roles_sistema or (role == "RH" and "ADMIN" in roles_sistema):
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
            if role in ("ADMIN", "SUPER_ADMIN", "RH"):
                return f(*args, **kwargs)
            permisos = get_permisos_for_role(mongo, role)
            if "*" in permisos or any(p in permisos for p in permisos_validos):
                return f(*args, **kwargs)
            return jsonify({"error": "Acceso no autorizado"}), 403
        return wrapper
    return decorator
