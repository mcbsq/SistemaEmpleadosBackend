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

logger = logging.getLogger(__name__)


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
