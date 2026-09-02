# api/tenants/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Registro central de empresas (tenants) dadas de alta en el sistema.
#
# Hoy una empresa nueva "nace" implícitamente: la primera persona que se
# loguea contra un tenant_id de Aegis que nunca ha tenido nadie en Mongo se
# auto-aprovisiona como SUPER_ADMIN (ver api/login/logic.py). Eso resuelve el
# aislamiento de datos, pero Cibercom no tenía ninguna vista para saber qué
# empresas existen, cuándo se dieron de alta, o su estado — este módulo es
# puramente esa capa de visibilidad, no toca el flujo de auto-provisioning.
#
# `tenants` es deliberadamente cross-tenant (una fila por CADA empresa), así
# que tanto la escritura (registrar_tenant, llamada desde el auto-provisioning)
# como la lectura (listar_tenants, para el operador) usan mongo.db.raw — el
# escape hatch documentado en core/tenant_db.py — para no quedar atadas al
# org_id de quien esté logueado en ese momento.
from datetime import datetime, timezone
import logging

from api.tenants.registration import RESERVED_SLUGS, normalize_slug
from core.mailer import build_tenant_login_url, send_temp_password_email

logger = logging.getLogger(__name__)


def crear_tenant_manual(mongo, payload):
    """Prepara un espacio vacío antes de crear su identidad administradora en Aegis."""
    nombre = (payload.get("nombre") or "").strip()
    org_id = normalize_slug(payload.get("org_id"))
    contacto_nombre = (payload.get("contacto_nombre") or "").strip()
    contacto_email = (payload.get("contacto_email") or "").strip().lower()

    if (
        not nombre or not contacto_nombre or "@" not in contacto_email
        or not 3 <= len(org_id) <= 63 or org_id in RESERVED_SLUGS
    ):
        return {"error": "invalid_company"}, 400

    raw = mongo.db.raw
    if raw.tenants.find_one({"org_id": org_id}):
        return {"error": "slug_unavailable"}, 409

    now = datetime.now(timezone.utc).isoformat()
    raw.organizacion.update_one(
        {"org_id": org_id},
        {"$setOnInsert": {"org_id": org_id, "name": nombre}},
        upsert=True,
    )
    raw.tenants.insert_one({
        "org_id": org_id,
        "nombre": nombre,
        "estado": "activo",
        "fecha_alta": now,
        "contacto_nombre": contacto_nombre,
        "contacto_email": contacto_email,
        "onboarding": "pendiente_primer_acceso",
    })
    return {
        "org_id": org_id,
        "nombre": nombre,
        "estado": "activo",
        "login_url": build_tenant_login_url(org_id),
        "onboarding": "pendiente_primer_acceso",
    }, 201


def enviar_acceso_tenant_manual(mongo, org_id, payload):
    """Entrega una contraseña generada en Aegis sin persistirla en Mongo."""
    raw = mongo.db.raw
    tenant = raw.tenants.find_one({"org_id": org_id})
    if not tenant or str(tenant.get("estado", "")).lower() not in {"activo", "active"}:
        return {"error": "tenant_not_found"}, 404

    email = (payload.get("email") or tenant.get("contacto_email") or "").strip().lower()
    usuario = (payload.get("usuario") or email).strip()
    temp_password = payload.get("temp_password") or ""
    if "@" not in email or not usuario or not temp_password:
        return {"error": "invalid_credentials_delivery"}, 400

    login_url = build_tenant_login_url(org_id)
    if not send_temp_password_email(email, usuario, temp_password, login_url=login_url):
        return {"error": "email_delivery_failed", "login_url": login_url}, 503

    raw.tenants.update_one(
        {"org_id": org_id},
        {"$set": {
            "onboarding": "credenciales_enviadas",
            "credenciales_enviadas_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {"email_sent": True, "email": email, "login_url": login_url}, 200


def registrar_tenant(mongo, org_id: str, nombre: str = None):
    """
    Da de alta la fila de registro de una empresa nueva. Se llama una sola vez,
    en el mismo momento en que se auto-aprovisiona su primer SUPER_ADMIN — es
    el único punto donde hoy "nace" un tenant nuevo.

    Idempotente a propósito (upsert + $setOnInsert): si por lo que sea se
    llama dos veces para el mismo org_id (ej. una condición de carrera con dos
    logins casi simultáneos del primer usuario), no se duplica la fila ni se
    pisa fecha_alta/estado ya existentes.
    """
    try:
        mongo.db.raw.tenants.update_one(
            {"org_id": org_id},
            {
                "$setOnInsert": {
                    "org_id": org_id,
                    "nombre": nombre or org_id,
                    "estado": "activo",
                    "fecha_alta": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
    except Exception as e:
        # No debe tumbar el login si esto falla — es un registro informativo,
        # no una condición para poder entrar al sistema.
        logger.error("No se pudo registrar el tenant '%s' en el catálogo: %s", org_id, e)


def listar_tenants(mongo):
    try:
        docs = list(mongo.db.raw.tenants.find({}).sort("fecha_alta", -1))
        for d in docs:
            d["_id"] = str(d["_id"])
        return docs
    except Exception as e:
        logger.error("Error listando tenants: %s", e)
        return []
