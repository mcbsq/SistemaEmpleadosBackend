# core/aegis_client.py
# ─────────────────────────────────────────────────────────────────────────────
# Cliente HTTP hacia el microservicio Aegis: autenticación de usuarios (login,
# /me) y operaciones de administración (crear usuario, reset de contraseña)
# usando ApiKey. Centraliza URLs, cabeceras y manejo básico de errores de red.
# ─────────────────────────────────────────────────────────────────────────────
import logging
from typing import Any, Optional, Tuple

import requests

from core.aegis_config import get_aegis_settings

logger = logging.getLogger(__name__)


def _auth_headers(access_token: str) -> dict:
    """Cabeceras para rutas que requieren sesión de usuario (JWT emitido por Aegis)."""
    s = get_aegis_settings()
    return {
        "X-Tenant-Id": s["tenant_id"],
        "X-App-Id": s["app_id"],
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _admin_headers() -> dict:
    """Cabeceras para la Admin API (sin Bearer de usuario; usa ApiKey de servicio)."""
    s = get_aegis_settings()
    return {
        "X-Tenant-Id": s["tenant_id"],
        "X-App-Id": s["app_id"],
        "Authorization": f"ApiKey {s['api_key']}",
        "Content-Type": "application/json",
    }


def aegis_resolve_tenant(identifier: str, app: str) -> Tuple[Optional[dict], Optional[Tuple[Any, int]]]:
    """
    Aegis ahora es multi-tenant: un mismo `identifier` puede existir en
    varios tenants, así que el tenant ya no se puede fijar por configuración
    estática. POST /v1/auth/resolve-tenant averigua a qué tenant pertenece
    este identifier para la app dada, ANTES de intentar login.
    Retorna ({"tenant_key","tenant_name","app_key","identifier_kind"}, None) si hay
    coincidencia única. Si falla: (None, (body, 404)) sin cuenta para esa app,
    o (None, (body, 409)) si el identifier existe en más de un tenant (Aegis
    aún no expone la lista de candidatos — el caller debe pedir aclaración).
    """
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/auth/resolve-tenant"
    try:
        r = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={"identifier": identifier.strip(), "app": app},
            timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis resolve-tenant: error de red: %s", e)
        return None, ({"error": "Servicio de autenticación no disponible"}, 503)

    if r.status_code == 200:
        return r.json(), None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return None, (err_body, r.status_code)


def aegis_password_login(
    identifier: str, password: str, tenant_id: Optional[str] = None, app_id: Optional[str] = None
) -> Tuple[Optional[dict], Optional[Tuple[dict, int]]]:
    """
    Valida credenciales contra Aegis. `tenant_id`/`app_id` permiten pasar el
    par resuelto dinámicamente vía resolve-tenant; si se omiten, cae en la
    configuración estática (compatibilidad con el tenant/app legacy).
    Retorna (tokens, None) si OK; si falla, (None, (cuerpo_error, código_http))
    para que login/logic decida mensaje al cliente o fallback legacy.
    """
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/auth/login"
    headers = {
        "X-Tenant-Id": tenant_id or s["tenant_id"],
        "X-App-Id": app_id or s["app_id"],
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            url,
            headers=headers,
            json={"identifier": identifier.strip(), "password": password},
            timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis login: error de red: %s", e)
        return None, ({"error": "Servicio de autenticación no disponible"}, 503)

    if r.status_code == 200:
        return r.json(), None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return None, (err_body, r.status_code)


def aegis_get_me(access_token: str, tenant_id: Optional[str] = None, app_id: Optional[str] = None) -> Tuple[Optional[dict], Optional[Tuple[Any, int]]]:
    """
    Obtiene id y email canónico del usuario autenticado en Aegis.
    Sirve para enlazar con la colección Mongo `usuario` (aegis_user_id / email / user).
    Debe usar el MISMO tenant/app con el que se hizo login (si se resolvió
    dinámicamente), de lo contrario Aegis no reconoce la sesión.
    """
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/me"
    headers = _auth_headers(access_token)
    if tenant_id:
        headers["X-Tenant-Id"] = tenant_id
    if app_id:
        headers["X-App-Id"] = app_id
    try:
        r = requests.get(url, headers=headers, timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis /v1/me: error de red: %s", e)
        return None, ({"error": "Servicio de autenticación no disponible"}, 503)

    if r.status_code == 200:
        return r.json(), None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return None, (err_body, r.status_code)


def aegis_admin_create_user(email: str, role: str = "empleado") -> Tuple[Optional[dict], Optional[Tuple[Any, int]]]:
    """
    Crea la identidad en Aegis antes (o en paralelo) de insertar en Mongo en POST /usuario.
    Aegis ya no acepta contraseña elegida por el admin: genera una temporal
    (retornada aquí como `temp_password`) que el usuario debe cambiar en su
    primer inicio de sesión.
    IMPORTANTE: sin `app_permissions` la cuenta se crea pero queda sin acceso
    a la app "empleados" — resolve-tenant no la encuentra y el login falla
    silenciosamente (este fue el bug reportado: "doy de alta en RH y no puede
    entrar"). `role` son permisos de negocio libres (cualquier string), no un
    catálogo fijo de Aegis — aquí se usa "admin" o "empleado".
    Retorna ({"id", "temp_password", "user"}, None) si OK.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return None, ({"error": "AEGIS_API_KEY no configurada"}, 503)

    url = f"{s['base_url']}/v1/admin/users"
    payload = {
        "email": email.strip().lower(),
        "is_active": True,
        "must_change_password": True,
        "temp_password_mode": "generate",
        "return_temp_password": True,
        "app_permissions": {
            s["app_id"]: {"scopes": ["users:read"], "roles": [role]},
        },
    }
    try:
        r = requests.post(url, headers=_admin_headers(), json=payload, timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis admin create user: %s", e)
        return None, ({"error": "Aegis admin no disponible"}, 503)

    if r.status_code in (200, 201):
        body = r.json()
        user = body.get("user") or {}
        return {
            "id": user.get("id"),
            "temp_password": body.get("temp_password"),
            "user": user,
        }, None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return None, (err_body, r.status_code)


def aegis_admin_reset_password(aegis_user_id: str) -> Tuple[Optional[str], Optional[Tuple[Any, int]]]:
    """
    Genera una contraseña temporal en Aegis (mode=temp_password) cuando el CRUD
    de empleados pide restablecer la contraseña en PUT /usuario. Aegis no
    permite fijar una contraseña arbitraria desde la Admin API.
    Retorna (temp_password, None) si OK; el usuario debe cambiarla al iniciar sesión.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return None, ({"error": "AEGIS_API_KEY no configurada"}, 503)

    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}/reset-password"
    try:
        r = requests.post(
            url,
            headers=_admin_headers(),
            json={"mode": "temp_password", "return_temp_password": True},
            timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis reset-password: %s", e)
        return None, ({"error": "Aegis admin no disponible"}, 503)

    if r.status_code in (200, 201):
        return (r.json() or {}).get("temp_password"), None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return None, (err_body, r.status_code)


def aegis_admin_list_users() -> Tuple[Optional[list], Optional[Tuple[Any, int]]]:
    """
    Lista todas las identidades del tenant en Aegis (pagina con limit/offset).
    Se usa para enriquecer GET /usuario con is_active y must_change_password.
    Retorna (lista_de_users, None) si OK.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return None, ({"error": "AEGIS_API_KEY no configurada"}, 503)

    url = f"{s['base_url']}/v1/admin/users"
    users, offset, limit = [], 0, 200
    while True:
        try:
            r = requests.get(
                url,
                headers=_admin_headers(),
                params={"limit": limit, "offset": offset},
                timeout=s["timeout"],
            )
        except requests.RequestException as e:
            logger.error("Aegis admin list users: %s", e)
            return None, ({"error": "Aegis admin no disponible"}, 503)

        if r.status_code != 200:
            try:
                err_body = r.json()
            except Exception:
                err_body = {"detail": r.text or r.reason}
            return None, (err_body, r.status_code)

        body = r.json()
        items = body.get("items", body if isinstance(body, list) else [])
        users.extend(items)
        if len(items) < limit:
            return users, None
        offset += limit


def aegis_admin_set_active(aegis_user_id: str, is_active: bool) -> Optional[Tuple[Any, int]]:
    """
    Activa/desactiva la identidad en Aegis (PATCH is_active). Se usa al borrar
    un usuario en Mongo para no dejar identidades huérfanas que sigan
    autenticando contra el IdP. Retorna None si OK.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return ({"error": "AEGIS_API_KEY no configurada"}, 503)

    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}"
    try:
        r = requests.patch(
            url,
            headers=_admin_headers(),
            json={"is_active": is_active},
            timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis set active: %s", e)
        return ({"error": "Aegis admin no disponible"}, 503)

    if r.status_code in (200, 204):
        return None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return (err_body, r.status_code)


def aegis_change_password(identifier: str, current_password: str, new_password: str) -> Optional[Tuple[Any, int]]:
    """
    Cambia la contraseña del propio usuario en Aegis: login con la contraseña
    actual y luego POST /v1/auth/change-password con el token obtenido.
    Sirve para exponer un /change-password en este backend sin almacenar
    tokens de Aegis. Retorna None si OK, o (cuerpo_error, código_http).
    """
    s = get_aegis_settings()
    tokens, err = aegis_password_login(identifier, current_password)
    if err:
        return err

    url = f"{s['base_url']}/v1/auth/change-password"
    try:
        r = requests.post(
            url,
            headers=_auth_headers(tokens["access_token"]),
            json={"current_password": current_password, "new_password": new_password},
            timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis change-password: %s", e)
        return ({"error": "Servicio de autenticación no disponible"}, 503)

    if r.status_code in (200, 204):
        return None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return (err_body, r.status_code)