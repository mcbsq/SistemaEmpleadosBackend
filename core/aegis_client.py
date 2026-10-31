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


def alcance_de_clave(tenant_id: Optional[str] = None) -> Optional[Tuple[dict, int]]:
    """
    La API key configurada pertenece al tenant de AEGIS_TENANT_ID.
    Mandar otro X-Tenant-Id no amplía ese alcance: la llamada se rechaza
    aquí, antes de salir, para no presentar la clave como si fuera global.
    """
    s = get_aegis_settings()
    clave = (s.get("tenant_id") or "").strip()
    pedido = (tenant_id or clave).strip()
    if pedido and clave and pedido != clave:
        logger.warning("Clave técnica fuera de su tenant configurado")
        return ({
            "error": "La clave técnica de Empleados no cubre esa empresa. "
                     "Cambiar el tenant no amplía su alcance.",
        }, 403)
    return None


def _admin_headers(tenant_id: Optional[str] = None) -> dict:
    """Cabeceras de la Admin API. El tenant es el de la clave, no uno arbitrario."""
    s = get_aegis_settings()
    return {
        "X-Tenant-Id": (tenant_id or s["tenant_id"] or "").strip(),
        "X-App-Id": s["app_id"],
        "Authorization": f"ApiKey {s['api_key']}",
        "Content-Type": "application/json",
    }


def _cuerpo(respuesta):
    """202 y 204 pueden venir vacíos. No se tratan como JSON inválido."""
    if respuesta.status_code in (202, 204):
        return {}
    texto = respuesta.content or b""
    if not texto.strip():
        return {}
    try:
        return respuesta.json()
    except Exception:
        return {"detail": respuesta.text or respuesta.reason}


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
        return _cuerpo(r), None
    return None, (_cuerpo(r), r.status_code)


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


def aegis_admin_create_user(email: str, role: str = "empleado", tenant_id: Optional[str] = None) -> Tuple[Optional[dict], Optional[Tuple[Any, int]]]:
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
    fuera = alcance_de_clave(tenant_id)
    if fuera:
        return None, fuera

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
        r = requests.post(url, headers=_admin_headers(tenant_id), json=payload, timeout=s["timeout"])
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


def aegis_admin_reset_password(aegis_user_id: str, tenant_id: Optional[str] = None) -> Tuple[Optional[str], Optional[Tuple[Any, int]]]:
    """
    Genera una contraseña temporal en Aegis (mode=temp_password) cuando el CRUD
    de empleados pide restablecer la contraseña en PUT /usuario. Aegis no
    permite fijar una contraseña arbitraria desde la Admin API.
    Retorna (temp_password, None) si OK; el usuario debe cambiarla al iniciar sesión.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return None, ({"error": "AEGIS_API_KEY no configurada"}, 503)
    fuera = alcance_de_clave(tenant_id)
    if fuera:
        return None, fuera

    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}/reset-password"
    try:
        r = requests.post(
            url,
            headers=_admin_headers(tenant_id),
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


def aegis_admin_list_users(tenant_id: Optional[str] = None) -> Tuple[Optional[list], Optional[Tuple[Any, int]]]:
    """
    Lista todas las identidades del tenant en Aegis (pagina con limit/offset).
    Se usa para enriquecer GET /usuario con is_active y must_change_password.
    Retorna (lista_de_users, None) si OK.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return None, ({"error": "AEGIS_API_KEY no configurada"}, 503)
    fuera = alcance_de_clave(tenant_id)
    if fuera:
        return None, fuera

    url = f"{s['base_url']}/v1/admin/users"
    users, offset, limit = [], 0, 200
    while True:
        try:
            r = requests.get(
                url,
                headers=_admin_headers(tenant_id),
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


def aegis_admin_set_active(aegis_user_id: str, is_active: bool, tenant_id: Optional[str] = None) -> Optional[Tuple[Any, int]]:
    """
    Activa/desactiva la identidad en Aegis (PATCH is_active). Se usa al borrar
    un usuario en Mongo para no dejar identidades huérfanas que sigan
    autenticando contra el IdP. Retorna None si OK.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return ({"error": "AEGIS_API_KEY no configurada"}, 503)
    fuera = alcance_de_clave(tenant_id)
    if fuera:
        return fuera

    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}"
    try:
        r = requests.patch(
            url,
            headers=_admin_headers(tenant_id),
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


def aegis_change_password(
    identifier: str, current_password: str, new_password: str,
    tenant_id: Optional[str] = None, app_id: Optional[str] = None,
) -> Optional[Tuple[Any, int]]:
    """
    Cambia la contraseña del propio usuario en Aegis: login con la contraseña
    actual y luego POST /v1/auth/change-password con el token obtenido.
    Sirve para exponer un /change-password en este backend sin almacenar
    tokens de Aegis. Retorna None si OK, o (cuerpo_error, código_http).

    `tenant_id`/`app_id`: SIN esto, el login interno caía en el tenant
    estático "cibercom" — para cualquier cuenta de una empresa cliente
    distinta, Aegis respondía 401 "credenciales inválidas" (el identifier
    no existe en cibercom) y el usuario veía "la contraseña que escribiste
    no es correcta" al definir su contraseña por primera vez, aunque la
    hubiera escrito bien (caso real: cuenta de Herramientas y Moldes
    Industriales, 2026-09-23). El caller debe pasar el org_id real del
    usuario (mongo.db.usuario.org_id, que es el tenant_key resuelto por
    Aegis en su login original).
    """
    s = get_aegis_settings()
    tokens, err = aegis_password_login(identifier, current_password, tenant_id=tenant_id, app_id=app_id)
    if err:
        return err

    url = f"{s['base_url']}/v1/auth/change-password"
    headers = _auth_headers(tokens["access_token"])
    headers["X-Tenant-Id"] = tenant_id or s["tenant_id"]
    headers["X-App-Id"] = app_id or s["app_id"]
    try:
        r = requests.post(
            url,
            headers=headers,
            json={"current_password": current_password, "new_password": new_password},
            timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis change-password: %s", e)
        return ({"error": "Servicio de autenticación no disponible"}, 503)

    if r.status_code in (200, 204):
        return None

    return (_cuerpo(r), r.status_code)


def aegis_get_access(access_token: str, tenant_id: Optional[str] = None, app_id: Optional[str] = None):
    """GET /v1/access. La decisión tiene que ser de la misma empresa y app que /v1/me."""
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/access"
    headers = _auth_headers(access_token)
    headers["X-Tenant-Id"] = tenant_id or s["tenant_id"]
    headers["X-App-Id"] = app_id or s["app_id"]
    try:
        r = requests.get(url, headers=headers, timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis /v1/access: error de red: %s", e)
        return None, ({"error": "Servicio de autenticación no disponible"}, 503)
    if r.status_code == 200:
        return _cuerpo(r), None
    return None, (_cuerpo(r), r.status_code)


def aegis_refresh(refresh_token: str, tenant_id: Optional[str] = None, app_id: Optional[str] = None):
    """POST /v1/auth/refresh. Hay que guardar el par nuevo; el anterior deja de servir."""
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/auth/refresh"
    headers = {
        "X-Tenant-Id": tenant_id or s["tenant_id"],
        "X-App-Id": app_id or s["app_id"],
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            url, headers=headers, json={"refresh_token": refresh_token}, timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis refresh: error de red: %s", e)
        return None, ({"error": "Servicio de autenticación no disponible"}, 503)
    if r.status_code == 200:
        return _cuerpo(r), None
    return None, (_cuerpo(r), r.status_code)


def aegis_logout(refresh_token: str, tenant_id: Optional[str] = None):
    """POST /v1/auth/logout. 204 vacío es éxito. No registra el token."""
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/auth/logout"
    headers = {
        "X-Tenant-Id": tenant_id or s["tenant_id"],
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            url, headers=headers, json={"refresh_token": refresh_token}, timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis logout: error de red: %s", e)
        return ({"error": "Servicio de autenticación no disponible"}, 503)
    if r.status_code in (200, 204):
        return None
    return (_cuerpo(r), r.status_code)


def aegis_password_reset_request(email: str, tenant_id: str):
    """
    POST /v1/auth/password-reset/request con el tenant de la liga conocida.
    No llama a resolve-tenant. 202 vacío es éxito y no dice si la cuenta existe.
    """
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/auth/password-reset/request"
    headers = {"X-Tenant-Id": tenant_id, "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=headers, json={"email": email}, timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis password-reset request: error de red: %s", e)
        return ({"error": "Servicio de autenticación no disponible"}, 503)
    if r.status_code == 202:
        return None
    return (_cuerpo(r), r.status_code)


def aegis_admin_retirar_acceso_producto(aegis_user_id: str, tenant_id: Optional[str] = None):
    """Quita solo el acceso de esta app. No desactiva ni borra la identidad global."""
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return ({"error": "AEGIS_API_KEY no configurada"}, 503)
    fuera = alcance_de_clave(tenant_id)
    if fuera:
        return fuera
    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}"
    cuerpo = {"app_permissions_patch": {s["app_id"]: {"roles": [], "scopes": []}}}
    try:
        r = requests.patch(url, headers=_admin_headers(tenant_id), json=cuerpo, timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis retirar acceso: %s", e)
        return ({"error": "Aegis admin no disponible"}, 503)
    if r.status_code in (200, 204):
        return None
    return (_cuerpo(r), r.status_code)


def aegis_admin_asignar_acceso_producto(
    aegis_user_id: str, role: str = "empleado", tenant_id: Optional[str] = None,
):
    """Vuelve a asignar solo la app de Empleados. No toca is_active global."""
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return ({"error": "AEGIS_API_KEY no configurada"}, 503)
    fuera = alcance_de_clave(tenant_id)
    if fuera:
        return fuera
    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}"
    cuerpo = {"app_permissions_patch": {s["app_id"]: {"roles": [role], "scopes": ["users:read"]}}}
    try:
        r = requests.patch(url, headers=_admin_headers(tenant_id), json=cuerpo, timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis asignar acceso: %s", e)
        return ({"error": "Aegis admin no disponible"}, 503)
    if r.status_code in (200, 204):
        return None
    return (_cuerpo(r), r.status_code)

def aegis_admin_recovery_email(aegis_user_id: str, tenant_id: Optional[str] = None) -> Optional[Tuple[Any, int]]:
    """
    POST /v1/admin/users/{id}/recovery-email: Aegis le manda a la persona su
    enlace de recuperación. Es lo que Aegis permite cuando niega generar una
    temporal para otra persona (403 en reset-password). Retorna None si OK.
    """
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return ({"error": "AEGIS_API_KEY no configurada"}, 503)
    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}/recovery-email"
    try:
        r = requests.post(url, headers=_admin_headers(tenant_id), timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis recovery-email: %s", e)
        return ({"error": "Aegis admin no disponible"}, 503)
    if r.status_code in (200, 201, 202, 204):
        return None
    return (_cuerpo(r), r.status_code)
