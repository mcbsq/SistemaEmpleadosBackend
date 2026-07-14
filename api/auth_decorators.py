# api/auth_decorators.py
#
# Decoradores de autorización reusables por rol, para no repetir la misma
# lógica ad-hoc (require_admin, require_super_admin, etc.) en cada blueprint.
# No usar require_self_or_roles en rutas donde "el propio recurso" no
# corresponda 1:1 con empleado_id del JWT — revisar caso por caso.

from functools import wraps
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt


def require_roles(*allowed_roles):
    """
    Uso: @require_roles('ADMIN', 'SUPER_ADMIN')
    Exige JWT válido y que el rol de la identidad esté en allowed_roles.
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt()
            role = identity.get('role') if isinstance(identity, dict) else None
            if role not in allowed_roles:
                return jsonify({"error": "Acceso no autorizado"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def require_self_or_roles(id_param, *allowed_roles):
    """
    Uso: @require_self_or_roles('id', 'ADMIN', 'SUPER_ADMIN')
    Permite el acceso si el rol está en allowed_roles, O si el valor de
    id_param en la URL coincide con el empleado_id del propio usuario.
    Pensado para rutas tipo /empleados/<id> donde un EMPLOYEE debe poder
    ver su propio registro pero no el de nadie más.
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt()
            role = identity.get('role') if isinstance(identity, dict) else None
            own_empleado_id = identity.get('empleado_id') if isinstance(identity, dict) else None
            requested_id = kwargs.get(id_param)

            if role in allowed_roles:
                return f(*args, **kwargs)
            if own_empleado_id and requested_id and str(own_empleado_id) == str(requested_id):
                return f(*args, **kwargs)
            return jsonify({"error": "Acceso no autorizado"}), 403
        return wrapper
    return decorator