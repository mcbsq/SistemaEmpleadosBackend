# Vínculo local ↔ Aegis por la pareja UUID de empresa + UUID de usuario.
# org_id sigue siendo la clave textual que ya usan los datos de Mongo.
# La correspondencia con el UUID de Aegis se guarda aparte y no reescribe
# los documentos de negocio.
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SLUGS_SIN_CONTRASTAR = (
    "herramientas-y-moldes-industriales",
    "herramientas_y_moldes_industriales",
)


def validar_correspondencia(mongo, org_id, aegis_tenant_id, app_key):
    """
    Registra org_id textual ↔ UUID de empresa si no había correspondencia.
    Si ya existe y no coincide, es un conflicto: no se enlaza ni se migra.
    """
    if not org_id or not aegis_tenant_id:
        return "incompleta"
    raw = mongo.db.raw
    actual = raw.tenant_correspondencia.find_one({"org_id": org_id, "app_key": app_key})
    if actual and actual.get("aegis_tenant_id") != aegis_tenant_id:
        logger.warning("Correspondencia incompatible para org_id=%s", org_id)
        return "conflicto"
    ajena = None
    for doc in raw.tenant_correspondencia.find({"aegis_tenant_id": aegis_tenant_id, "app_key": app_key}):
        if doc.get("org_id") != org_id:
            ajena = doc
            break
    if ajena:
        logger.warning("UUID de empresa ya ligado a otro org_id")
        return "conflicto"
    if not actual:
        raw.tenant_correspondencia.insert_one({
            "org_id": org_id,
            "aegis_tenant_id": aegis_tenant_id,
            "app_key": app_key,
            "confirmado_en": datetime.now(timezone.utc).isoformat(),
        })
    return "ok"


def buscar_usuario_por_par(mongo, aegis_user_id, aegis_tenant_id, org_id):
    """
    Solo la pareja UUID empresa + UUID usuario, y solo si el org textual
    coincide. No usa el correo. No escribe: el login no rellena campos.
    Dos filas o una fila de otra empresa son conflicto, no «la primera».
    """
    if not aegis_user_id or not aegis_tenant_id or not org_id:
        return None
    raw = mongo.db.raw
    variantes = {aegis_user_id, str(aegis_user_id)}
    vistos = []
    ids = set()
    for doc in raw.usuario.find({"aegis_user_id": {"$in": list(variantes)}}):
        clave = str(doc.get("_id"))
        if clave in ids:
            continue
        tenant_doc = doc.get("aegis_tenant_id")
        if tenant_doc not in (None, "", aegis_tenant_id):
            continue
        org_doc = doc.get("org_id") or ""
        if tenant_doc in (None, "") and org_doc != org_id:
            continue
        if tenant_doc == aegis_tenant_id and org_doc and org_doc != org_id:
            return None
        ids.add(clave)
        vistos.append(doc)
    if len(vistos) != 1:
        return None
    if (vistos[0].get("org_id") or "") != org_id:
        return None
    return vistos[0]


def _correo(valor):
    return str(valor or "").strip().lower()


def plan_vinculos(usuarios, identidades=None):
    """
    Dry-run. No escribe. identidades es una lista opcional ya obtenida fuera
    de este proceso: {email, user_id, tenant_id, org_id, app_key, activo}.
    El rol propuesto es el rol local actual. Una cuenta inactiva sigue inactiva.
    """
    identidades = list(identidades or [])
    por_correo = {}
    for identidad in identidades:
        por_correo.setdefault(_correo(identidad.get("email")), []).append(identidad)

    filas = []
    locales_por_correo = {}
    for usuario in usuarios or []:
        correo = _correo(usuario.get("email"))
        if correo:
            locales_por_correo.setdefault(correo, []).append(usuario)

    orgs = {str(u.get("org_id") or "") for u in (usuarios or [])}
    for usuario in usuarios or []:
        correo = _correo(usuario.get("email"))
        org_id = usuario.get("org_id") or ""
        rol = usuario.get("role") or ""
        activo = usuario.get("activo") is not False
        uuid_local = usuario.get("aegis_user_id") or ""
        tenant_local = usuario.get("aegis_tenant_id") or ""
        conflictos = []
        candidatos = [i for i in por_correo.get(correo, []) if correo]
        if len(locales_por_correo.get(correo, [])) > 1:
            conflictos.append("correo_repetido_entre_cuentas_locales")
        if uuid_local and candidatos:
            ajenos = [i for i in candidatos if str(i.get("user_id")) != str(uuid_local)]
            if ajenos:
                conflictos.append("correo_con_uuid_incompatible")
        if not uuid_local and len(candidatos) > 1:
            conflictos.append("correo_ambiguo_en_aegis")
        if not uuid_local and len(candidatos) == 1:
            unico = candidatos[0]
            if unico.get("org_id") and unico.get("org_id") != org_id:
                conflictos.append("correo_apunta_a_otra_empresa")
        parte = correo.split("@", 1)[0] if "@" in correo else ""
        if parte:
            for otro in usuarios or []:
                otro_correo = _correo(otro.get("email"))
                if otro is usuario or "@" not in otro_correo:
                    continue
                if otro_correo.split("@", 1)[0] == parte and otro_correo != correo:
                    conflictos.append("alias_igual_en_otro_dominio")
                    break
        propuesto = ""
        if not conflictos and not uuid_local and len(candidatos) == 1:
            unico = candidatos[0]
            if not unico.get("org_id") or unico.get("org_id") == org_id:
                propuesto = str(unico.get("user_id") or "")
        filas.append({
            "org_id_actual": org_id,
            "org_id_destino": org_id,
            "app_actual": usuario.get("app_key") or "",
            "app_destino": "empleados",
            "aegis_user_id": uuid_local,
            "aegis_user_id_propuesto": propuesto,
            "aegis_tenant_id": tenant_local,
            "vinculo_local": str(usuario.get("_id") or usuario.get("user") or ""),
            "rol_actual": rol,
            "rol_propuesto": rol,
            "activo": activo,
            "estado": "inactiva" if not activo else ("conflicto" if conflictos else ("vinculada" if uuid_local else "pendiente")),
            "conflictos": conflictos,
        })

    notas = []
    presentes = SLUGS_SIN_CONTRASTAR
    if all(slug in orgs for slug in presentes):
        notas.append(
            "Coexisten herramientas-y-moldes-industriales y "
            "herramientas_y_moldes_industriales. No retirar ninguna hasta "
            "contrastar Mongo con Aegis. El ejemplo de overrides no demuestra "
            "cuál valor está desplegado."
        )
    return {"filas": filas, "notas": notas, "aplicado": False}
