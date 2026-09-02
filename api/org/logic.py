# api/org/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Configuración de la organización: identidad/marca, módulos activos, KPIs, y
# reglas de negocio configurables por SUPER_ADMIN (política de vacaciones,
# quién las aprueba). El frontend (OrgContext.js) ya existía apuntando a esta
# ruta; nunca había tenido backend — esto es lo que lo activa de verdad.
#
# Diseño pensado para reventa: todo lo que antes era una constante en código
# (tabla de vacaciones, roles aprobadores, módulos visibles, colores) vive
# aquí como datos, editable sin tocar una línea de Python.
from flask import jsonify
import logging

from core.aegis_config import get_aegis_settings

logger = logging.getLogger(__name__)

# Tabla de vacaciones por antigüedad — art. 76 LFT (México) como default
# razonable. 100% editable desde Configuración → Vacaciones.
DEFAULT_TABLA_VACACIONES = {
    "1": 12, "2": 14, "3": 16, "4": 18, "5": 20,
    "6": 22, "10": 24, "15": 26, "20": 28, "25": 30, "30": 32,
}

DEFAULT_CONFIG = {
    "org_id": "default",
    "name": "CibercomHR",
    "logo": None,
    "branding": {
        "primaryColor": "#5B8AF0",
        "secondaryColor": "#4ECAAC",
        "accentColor": "#9B7FE8",
    },
    "modules": {
        "home_carousel": True,
        "organigrama": True,
        "empleados_table": True,
        "dashboard_admin": True,
        "dashboard_rh": True,
        "dashboard_medico": False,
        "dashboard_pm": False,
        "dashboard_contador": False,
        "dashboard_jefe_area": False,
        "incident_monitor": False,
        "global_search": True,
        "vacaciones": True,
        "prestamos": True,
        "documentos_financieros": True,
    },
    "kpis": [
        {"id": "total_empleados", "label": "Total empleados", "visible": True, "color": "#5B8AF0"},
        {"id": "areas_registradas", "label": "Áreas registradas", "visible": True, "color": "#4ECAAC"},
        {"id": "cumpleanos_mes", "label": "Cumpleaños este mes", "visible": True, "color": "#F5A623"},
        {"id": "sin_expediente", "label": "Sin expediente", "visible": True, "color": "#E86B5F"},
        {"id": "sin_puesto", "label": "Sin puesto asignado", "visible": False, "color": "#9B7FE8"},
    ],
    "customFields": [],
    "roles": ["SUPER_ADMIN", "ADMIN", "EMPLOYEE"],
    # ── Reglas de negocio configurables ──
    "vacaciones": {
        "tabla_dias_por_antiguedad": DEFAULT_TABLA_VACACIONES,
        "roles_aprueban": ["ADMIN", "SUPER_ADMIN"],
        "notificar_por_correo": True,
    },
}


def _merge_deep(base, override):
    """Merge recursivo: override gana, pero nunca borra claves que no toca."""
    result = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge_deep(result[k], v)
        else:
            result[k] = v
    return result


def get_config(mongo, org_id):
    try:
        doc = mongo.db.organizacion.find_one({"org_id": org_id})
        config = _merge_deep(DEFAULT_CONFIG, doc or {})
        config["org_id"] = org_id
        config.pop("_id", None)
        # Existencia real del tenant: usada por la pantalla de login por URL
        # (/<org_id>) para distinguir "empresa real, branding por default
        # porque aún no personalizó nada" de "org_id inventado en la URL que
        # nunca se ha logueado nadie". El tenant propio de Cibercom siempre
        # existe (es el original, nunca pasó por el auto-provisioning nuevo).
        # Se usa mongo.db.raw porque esta ruta es pública (sin g.org_id) y la
        # pregunta es deliberadamente sobre CUALQUIER tenant, no el propio.
        tenant_cibercom = get_aegis_settings()["tenant_id"] or "cibercom"
        tenant = mongo.db.raw.tenants.find_one({"org_id": org_id})
        tenant_activo = bool(
            tenant and str(tenant.get("estado", "")).strip().lower() in {"active", "activo"}
        )
        config["existe"] = (
            org_id == tenant_cibercom
            or tenant_activo
            # Compatibilidad con empresas históricas creadas antes del catálogo.
            or mongo.db.raw.usuario.count_documents({"org_id": org_id}) > 0
        )
        return jsonify(config), 200
    except Exception as e:
        logger.error(f"Error obteniendo config de organización: {e}")
        return jsonify(DEFAULT_CONFIG), 200


def update_config(mongo, org_id, updates):
    try:
        if not isinstance(updates, dict):
            return jsonify({"error": "Cuerpo inválido"}), 400
        updates.pop("_id", None)
        updates.pop("org_id", None)
        mongo.db.organizacion.update_one(
            {"org_id": org_id}, {"$set": updates}, upsert=True
        )
        return get_config(mongo, org_id)
    except Exception as e:
        logger.error(f"Error actualizando config de organización: {e}")
        return jsonify({"error": str(e)}), 500


def get_vacaciones_config(mongo, org_id="default"):
    """Helper interno para otros módulos (vacaciones) — no es una ruta HTTP."""
    doc = mongo.db.organizacion.find_one({"org_id": org_id}) or {}
    merged = _merge_deep(DEFAULT_CONFIG, doc)
    return merged["vacaciones"]
