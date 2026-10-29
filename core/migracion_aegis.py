# Sesiones abiertas con la app anterior de Aegis durante la migración
# (ver core/aegis_config.py: AEGIS_MIGRACION_LEGACY). Esas cuentas todavía no
# tienen perfiles de "empleados" en /v1/access, así que se comportan como
# antes de la integración: el rol sale de Mongo y no se revalida el acceso a
# "empleados" en cada petición. La sesión, la cookie, el CSRF y la
# renovación con refresh de Aegis sí aplican igual.
from core.aegis_config import get_aegis_settings
from core.perfiles_aegis import APP_KEY


def es_sesion_legacy(sesion):
    if not sesion:
        return False
    app = sesion.get("app_key")
    return bool(app) and app != APP_KEY and bool(get_aegis_settings().get("migracion"))
