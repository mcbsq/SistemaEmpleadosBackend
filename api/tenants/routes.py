# api/tenants/routes.py
from functools import wraps
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt

from .logic import listar_tenants
from core.aegis_config import get_aegis_settings


def _require_operador_cibercom(f):
    """
    Autorización deliberadamente distinta de @require_roles: SUPER_ADMIN por
    sí solo no basta, porque cada empresa cliente también tiene el suyo — ese
    rol existe una vez POR TENANT, no identifica a Cibercom como operador de
    la plataforma.

    En vez de inventar un rol de plataforma nuevo (cambio más grande al
    modelo de permisos), se reutiliza lo que ya existe: el tenant propio de
    Cibercom (settings["tenant_id"], el mismo que usa el login legacy) es una
    empresa más dentro del mismo sistema. Un SUPER_ADMIN CUYO org_id sea ese
    tenant es, por definición, alguien operando dentro del espacio de
    Cibercom — nadie de una empresa cliente puede tener ese org_id en su JWT.
    """
    @wraps(f)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        role = claims.get('role') if isinstance(claims, dict) else None
        org_id = claims.get('org_id') if isinstance(claims, dict) else None
        tenant_cibercom = get_aegis_settings()["tenant_id"] or "cibercom"
        if role != 'SUPER_ADMIN' or org_id != tenant_cibercom:
            return jsonify({"error": "Acceso no autorizado"}), 403
        return f(*args, **kwargs)
    return wrapper


def setup_tenants_routes(app, mongo):

    # Registro central de empresas — solo Cibercom (SUPER_ADMIN del tenant
    # propio de Cibercom) puede ver qué empresas existen en el sistema.
    @app.route('/admin/tenants', methods=['GET'])
    @_require_operador_cibercom
    def listar_tenants_route():
        return jsonify(listar_tenants(mongo)), 200
