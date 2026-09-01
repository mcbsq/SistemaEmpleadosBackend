import re
import unicodedata
from datetime import datetime, timezone

from core.tenant_provisioning import IdentityProviderUnavailable


RESERVED_SLUGS = {"login", "registro", "dashboard", "empleados", "vacaciones", "nomina", "api", "settings", "roles", "tenants", "monitor", "perfil"}


def normalize_slug(value):
    text = unicodedata.normalize("NFD", (value or "").strip().lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text)).strip("-")


def slug_availability(mongo, value):
    slug = normalize_slug(value)
    available = (
        3 <= len(slug) <= 63
        and slug not in RESERVED_SLUGS
        and mongo.db.raw.tenants.find_one({"org_id": slug}) is None
    )
    return {"slug": slug, "available": available}


def register_tenant(mongo, payload, provisioner):
    raw = mongo.db.raw
    company = (payload.get("company_name") or "").strip()
    slug = normalize_slug(payload.get("slug"))
    email = (payload.get("admin_email") or "").strip().lower()
    password = payload.get("password") or ""
    if not company or len(slug) < 3 or slug in RESERVED_SLUGS or "@" not in email or len(password) < 12:
        return {"error": "invalid_registration"}, 400
    existing = raw.tenants.find_one({"org_id": slug})
    if existing:
        return {"slug": slug, "status": existing.get("estado", "active"), "login_url": f"/{slug}"}, 200
    try:
        identity = provisioner.provision(company_name=company, slug=slug, admin_name=(payload.get("admin_name") or "").strip(), admin_email=email, password=password)
    except IdentityProviderUnavailable:
        return {"error": "identity_provider_unavailable"}, 503
    now = datetime.now(timezone.utc).isoformat()
    raw.organizacion.update_one({"org_id": slug}, {"$setOnInsert": {"org_id": slug, "name": company}}, upsert=True)
    raw.usuario.update_one({"org_id": slug, "email": email}, {"$setOnInsert": {"org_id": slug, "email": email, "user": email.split("@", 1)[0], "name": payload.get("admin_name"), "role": "SUPER_ADMIN", "aegis_user_id": identity.get("user_id")}}, upsert=True)
    raw.tenants.update_one({"org_id": slug}, {"$setOnInsert": {"org_id": slug, "nombre": company, "estado": "active", "fecha_alta": now}}, upsert=True)
    return {"slug": slug, "status": "active", "login_url": f"/{slug}"}, 201
