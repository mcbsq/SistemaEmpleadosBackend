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
        "Authorization": f"ApiKey {s['api_key']}",
        "Content-Type": "application/json",
    }


def aegis_password_login(identifier: str, password: str) -> Tuple[Optional[dict], Optional[Tuple[dict, int]]]:
    """
    Valida credenciales contra Aegis (mismo contrato que el front podría usar directo).
    Retorna (tokens, None) si OK; si falla, (None, (cuerpo_error, código_http))
    para que login/logic decida mensaje al cliente o fallback legacy.
    """
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/auth/login"
    headers = {
        "X-Tenant-Id": s["tenant_id"],
        "X-App-Id": s["app_id"],
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


def aegis_get_me(access_token: str) -> Tuple[Optional[dict], Optional[Tuple[Any, int]]]:
    """
    Obtiene id y email canónico del usuario autenticado en Aegis.
    Sirve para enlazar con la colección Mongo `usuario` (aegis_user_id / email / user).
    """
    s = get_aegis_settings()
    url = f"{s['base_url']}/v1/me"
    try:
        r = requests.get(url, headers=_auth_headers(access_token), timeout=s["timeout"])
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


def aegis_admin_create_user(email: str, password: str) -> Tuple[Optional[dict], Optional[Tuple[Any, int]]]:
    """Crea la identidad en Aegis antes (o en paralelo) de insertar en Mongo en POST /usuario."""
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return None, ({"error": "AEGIS_API_KEY no configurada"}, 503)

    url = f"{s['base_url']}/v1/admin/users"
    payload = {"email": email.strip().lower(), "password": password, "is_active": True}
    try:
        r = requests.post(url, headers=_admin_headers(), json=payload, timeout=s["timeout"])
    except requests.RequestException as e:
        logger.error("Aegis admin create user: %s", e)
        return None, ({"error": "Aegis admin no disponible"}, 503)

    if r.status_code in (200, 201):
        return r.json(), None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return None, (err_body, r.status_code)


def aegis_admin_reset_password(aegis_user_id: str, new_password: str) -> Optional[Tuple[Any, int]]:
    """Actualiza la contraseña solo en Aegis cuando el CRUD de empleados envía password en PUT /usuario."""
    s = get_aegis_settings()
    if not s["admin_enabled"]:
        return ({"error": "AEGIS_API_KEY no configurada"}, 503)

    url = f"{s['base_url']}/v1/admin/users/{aegis_user_id}/reset-password"
    try:
        r = requests.post(
            url,
            headers=_admin_headers(),
            json={"new_password": new_password},
            timeout=s["timeout"],
        )
    except requests.RequestException as e:
        logger.error("Aegis reset-password: %s", e)
        return ({"error": "Aegis admin no disponible"}, 503)

    if r.status_code in (200, 201, 204):
        return None

    try:
        err_body = r.json()
    except Exception:
        err_body = {"detail": r.text or r.reason}
    return (err_body, r.status_code)
