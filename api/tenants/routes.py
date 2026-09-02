# api/tenants/routes.py
from functools import wraps
import os

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt

from .logic import crear_tenant_manual, enviar_acceso_tenant_manual, listar_tenants
from .registration import register_tenant, slug_availability
from core.aegis_config import get_aegis_settings
from core.public_rate_limit import RegistrationRateLimiter
from core.tenant_provisioning import UnavailableTenantProvisioner


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

    app.config.setdefault(
        "PUBLIC_REGISTRATION_ENABLED",
        os.environ.get("PUBLIC_REGISTRATION_ENABLED", "false").lower() == "true",
    )
    app.config.setdefault("REGISTRATION_RATE_LIMITER", RegistrationRateLimiter())

    @app.route('/public/tenants/slug-availability', methods=['GET'])
    def slug_availability_route():
        return jsonify(slug_availability(mongo, request.args.get("slug", ""))), 200

    @app.route('/public/tenants/register', methods=['POST'])
    def register_tenant_route():
        if not app.config["PUBLIC_REGISTRATION_ENABLED"]:
            return jsonify({"error": "registration_disabled"}), 503
        if not app.config["REGISTRATION_RATE_LIMITER"].allow(request.remote_addr or "unknown"):
            return jsonify({"error": "rate_limited"}), 429
        body, status = register_tenant(
            mongo,
            request.get_json(silent=True) or {},
            app.config.get("TENANT_PROVISIONER") or UnavailableTenantProvisioner(),
        )
        return jsonify(body), status

    # Registro central de empresas — solo Cibercom (SUPER_ADMIN del tenant
    # propio de Cibercom) puede ver qué empresas existen en el sistema.
    @app.route('/admin/tenants', methods=['GET'])
    @_require_operador_cibercom
    def listar_tenants_route():
        return jsonify(listar_tenants(mongo)), 200

    @app.route('/admin/tenants', methods=['POST'])
    @_require_operador_cibercom
    def crear_tenant_manual_route():
        body, status = crear_tenant_manual(mongo, request.get_json(silent=True) or {})
        return jsonify(body), status

    @app.route('/admin/tenants/<org_id>/deliver-access', methods=['POST'])
    @_require_operador_cibercom
    def enviar_acceso_tenant_manual_route(org_id):
        body, status = enviar_acceso_tenant_manual(
            mongo, org_id, request.get_json(silent=True) or {},
        )
        return jsonify(body), status
