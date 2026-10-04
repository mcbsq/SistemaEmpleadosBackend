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


def es_operador_plataforma(claims):
    """Cuenta suprema de la plataforma: SUPER_ADMIN del tenant de Cibercom
    con la marca explícita `plataforma` (oct 2026). Antes bastaba con ser
    SUPER_ADMIN de Cibercom, lo que mezclaba al administrador de la EMPRESA
    Cibercom con el dueño de la aplicación."""
    if not isinstance(claims, dict):
        return False
    tenant_cibercom = get_aegis_settings()["tenant_id"] or "cibercom"
    return bool(claims.get('plataforma')) and claims.get('role') == 'SUPER_ADMIN' and claims.get('org_id') == tenant_cibercom


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
        if not es_operador_plataforma(claims):
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


    # Resumen por empresa para las tarjetas de "Empresas" — solo conteos de
    # uso, nunca datos personales de nadie.
    @app.route('/admin/tenants/resumen', methods=['GET'])
    @_require_operador_cibercom
    def resumen_tenants_route():
        raw = mongo.db.raw
        def contar(col, extra=None):
            pipeline = [{"$match": extra or {}}, {"$group": {"_id": "$org_id", "n": {"$sum": 1}}}]
            return {d["_id"]: d["n"] for d in raw[col].aggregate(pipeline)}
        empleados = contar("empleados", {"estado": {"$ne": "pendiente"}})
        usuarios = contar("usuario")
        solicitudes = contar("solicitudes_rh", {"estado": {"$in": ["abierta", "en_proceso"]}})
        ultima = {d["_id"]: d["f"] for d in raw.auditoria.aggregate([{"$group": {"_id": "$org_id", "f": {"$max": "$creado_en"}}}])}
        orgs = set(empleados) | set(usuarios) | {t.get("org_id") for t in raw.tenants.find({}, {"org_id": 1})}
        return jsonify({o: {"empleados": empleados.get(o, 0), "cuentas": usuarios.get(o, 0),
                            "solicitudes_abiertas": solicitudes.get(o, 0), "ultima_actividad": ultima.get(o)}
                        for o in orgs if o}), 200

    # Entrar a ver el "universo" de una empresa (modo soporte, solo lectura).
    # Queda registrado EN LA AUDITORÍA DE ESA EMPRESA, a la vista de su
    # administrador: Cibercom nunca entra sin dejar rastro.
    @app.route('/admin/tenants/<org_id>/entrar', methods=['POST'])
    @_require_operador_cibercom
    def entrar_universo_route(org_id):
        from datetime import datetime, timezone
        tenant = mongo.db.raw.tenants.find_one({"org_id": org_id})
        tenant_cibercom = get_aegis_settings()["tenant_id"] or "cibercom"
        if not tenant and org_id != tenant_cibercom and not mongo.db.raw.usuario.find_one({"org_id": org_id}):
            return jsonify({"error": "Esa empresa no existe."}), 404
        claims = get_jwt()
        mongo.db.raw.auditoria.insert_one({
            "org_id": org_id, "usuario": claims.get("user"), "role": "PLATAFORMA", "accion": "acceso",
            "entidad": "modo_soporte", "entidad_id": "", "creado_en": datetime.now(timezone.utc).isoformat(),
            "detalle": "Cibercom entró a ver esta empresa en modo soporte (solo lectura).",
        })
        return jsonify({"org_id": org_id, "nombre": (tenant or {}).get("nombre") or org_id}), 200
