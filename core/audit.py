# core/audit.py
# ─────────────────────────────────────────────────────────────────────────────
# Auditoría de cambios: quién cambió qué campo y cuándo, en datos sensibles
# (empleados, RH, roles, usuarios). Compliance básico — sin esto, nadie puede
# responder "¿quién cambió el sueldo de fulano la semana pasada?".
from datetime import datetime, timezone
from bson.objectid import ObjectId
import logging

logger = logging.getLogger(__name__)

# Campos que nunca se guardan en claro en el log (aunque cambien) — por si
# algún módulo futuro los incluye en un "antes/después" de un documento
# completo en vez de campo por campo.
_CAMPOS_SENSIBLES_OCULTOS = {"password", "key_hash"}


def _limpiar(valor):
    if isinstance(valor, ObjectId):
        return str(valor)
    return valor


def diff_documentos(doc_antes, doc_despues):
    """
    Compara dos dicts al nivel superior y regresa {campo: {antes, despues}}
    solo para los campos que realmente cambiaron. No es un deep-diff — es
    suficiente para los documentos planos que maneja este sistema.
    """
    antes = doc_antes or {}
    despues = doc_despues or {}
    campos = set(antes.keys()) | set(despues.keys())
    cambios = {}
    for campo in campos:
        if campo in ("_id",) or campo in _CAMPOS_SENSIBLES_OCULTOS:
            continue
        va, vd = _limpiar(antes.get(campo)), _limpiar(despues.get(campo))
        if va != vd:
            cambios[campo] = {"antes": va, "despues": vd}
    return cambios


def registrar_auditoria(mongo, usuario, role, accion, entidad, entidad_id, cambios=None, detalle=None):
    """
    Uso: registrar_auditoria(mongo, 'admin_test', 'ADMIN', 'update',
                              'empleados', str(id), cambios=diff_documentos(antes, despues))
    No lanza si falla — un log perdido no debe tumbar la operación que audita.
    """
    try:
        mongo.db.audit_log.insert_one({
            "usuario": usuario,
            "role": role,
            "accion": accion,       # create | update | delete
            "entidad": entidad,     # empleados | rh | roles_custom | usuario | ...
            "entidad_id": str(entidad_id) if entidad_id else None,
            "cambios": cambios or {},
            "detalle": detalle,
            "creado_en": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"No se pudo registrar auditoría ({entidad}/{accion}): {e}")
