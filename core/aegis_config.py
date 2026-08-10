# core/aegis_config.py
# ─────────────────────────────────────────────────────────────────────────────
# Lee variables de entorno y decide si este backend debe usar Aegis para login
# y/o para crear/resetear contraseñas (Admin API). El resto del código no
# repite la lógica de "¿hay URL? ¿hay API key?": solo consulta get_aegis_settings().
# ─────────────────────────────────────────────────────────────────────────────
import os


def _truthy(value, default=False):
    """Interpreta strings tipo 'true' / '1' como booleano (útil en .env)."""
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_aegis_settings():
    """
    Devuelve un dict con la configuración efectiva.
    - login_enabled: hay URL + tenant + app y no se forzó AEGIS_DISABLED.
      Si es True, /login habla con Aegis en lugar de validar hash en Mongo.
    - admin_enabled: además existe AEGIS_API_KEY; permite POST /usuario y
      cambio de contraseña vía reset-password en Aegis.
    """
    base = (os.environ.get("AEGIS_BASE_URL") or "").strip().rstrip("/")
    tenant_id = (os.environ.get("AEGIS_TENANT_ID") or "").strip()
    api_key = (os.environ.get("AEGIS_API_KEY") or "").strip()
    timeout = float(os.environ.get("AEGIS_TIMEOUT") or "15")

    # Aegis pasó a multi-tenant/multi-app: "empleados" es la app registrada en
    # el catálogo nuevo (resolve-tenant + app_permissions al crear usuarios).
    # "principal" es la app legacy con la que se crearon las cuentas de este
    # backend antes de ese cambio — sigue autenticando por login directo, pero
    # resolve-tenant no la reconoce. Se usa solo como último recurso.
    app_id = (os.environ.get("AEGIS_APP_ID") or "empleados").strip()
    legacy_app_id = (os.environ.get("AEGIS_LEGACY_APP_ID") or "principal").strip()

    # Si Aegis rechaza credenciales o no responde, ¿intentamos login viejo con Mongo?
    legacy_fallback = _truthy(os.environ.get("AEGIS_LEGACY_LOGIN_FALLBACK"), False)
    explicit_off = _truthy(os.environ.get("AEGIS_DISABLED"), False)
    login_enabled = bool(base and tenant_id and app_id) and not explicit_off
    admin_enabled = login_enabled and bool(api_key)
    return {
        "base_url": base,
        "tenant_id": tenant_id,
        "app_id": app_id,
        "legacy_app_id": legacy_app_id,
        "api_key": api_key,
        "timeout": timeout,
        "legacy_fallback": legacy_fallback,
        "login_enabled": login_enabled,
        "admin_enabled": admin_enabled,
    }