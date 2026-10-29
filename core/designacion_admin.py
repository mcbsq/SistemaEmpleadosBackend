# Primera cuenta DESIGNATED de una empresa vacía. No basta con ser quien
# entra primero: el perfil de Aegis tiene que ser administrador de Empleados.
# El índice único de designacion_admin.org_id (script de migración, no
# aplicado aquí) y find_one_and_update cubren dos workers. Un candado de
# hilo no alcanza cuando gunicorn tiene workers = 4.
from datetime import datetime, timezone

from core.perfiles_aegis import clasificar_perfiles
from core.vinculo_identidad import buscar_usuario_por_par


def _duplicado(exc):
    return exc.__class__.__name__ == "DuplicateKeyError"


def designar_si_corresponde(mongo, org_id, perfil, roles):
    if clasificar_perfiles(roles) != "administrador":
        return None
    uid = str(perfil.get("id") or "")
    tenant_uuid = str(perfil.get("tenant_id") or "")
    if not uid or not tenant_uuid or not org_id:
        return None
    email = (perfil.get("email") or "").strip().lower()
    raw = mongo.db.raw
    marca = {
        "org_id": org_id,
        "aegis_user_id": uid,
        "aegis_tenant_id": tenant_uuid,
        "designado_en": datetime.now(timezone.utc).isoformat(),
    }
    try:
        previo = raw.designacion_admin.find_one_and_update(
            {"org_id": org_id},
            {"$setOnInsert": marca},
            upsert=True,
        )
    except Exception as exc:
        if not _duplicado(exc):
            raise
        previo = raw.designacion_admin.find_one({"org_id": org_id})
    if previo and str(previo.get("aegis_user_id")) != uid:
        return None
    existente = buscar_usuario_por_par(mongo, uid, tenant_uuid, org_id)
    if existente:
        return existente
    if raw.usuario.count_documents({"org_id": org_id}) > 0:
        return None
    local = email.split("@", 1)[0] if "@" in email else f"admin_{org_id}"
    doc = {
        "user": local[:80] or f"admin_{org_id}",
        "role": "SUPER_ADMIN",
        "plataforma": False,
        "empleado_id": None,
        "email": email or None,
        "aegis_user_id": uid,
        "aegis_tenant_id": tenant_uuid,
        "org_id": org_id,
        "activo": True,
    }
    try:
        raw.usuario.insert_one(doc)
    except Exception as exc:
        if not _duplicado(exc):
            raise
        return buscar_usuario_por_par(mongo, uid, tenant_uuid, org_id)
    return doc
