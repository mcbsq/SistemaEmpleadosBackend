# core/conexiones_externas.py
# ─────────────────────────────────────────────────────────────────────────────
# Consumo de API keys AJENAS (de otros sistemas) — lo opuesto al módulo
# api/apikeys/ (que valida keys que otros nos mandan a NOSOTROS). Caso de uso
# pedido: la nómina se genera en otro sistema; este backend guarda la
# credencial de ESE sistema y, al abrir el perfil de un empleado, jala su
# nómina en vivo desde allá para mostrarla — sin duplicar el dato aquí.
#
# A diferencia de api/apikeys/ (que solo guarda un hash SHA-256, porque nunca
# necesita recuperar el valor), aquí SÍ hace falta poder leer la key en claro
# para mandarla al sistema externo — un hash de una sola vía no sirve. Se usa
# cifrado simétrico reversible (Fernet/AES) con una clave de app, nunca texto
# plano en Mongo.
from __future__ import annotations
import base64
import hashlib
import logging
import os

import requests
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    """
    Deriva una clave Fernet válida (32 bytes urlsafe-base64) a partir de
    EXTERNAL_CREDENTIALS_SECRET. Sin ese secreto en el entorno, cae a
    JWT_SECRET_KEY (ya obligatorio para arrancar) para no añadir una segunda
    variable requerida — pero se recomienda fijar una propia en producción,
    ya que rotar JWT_SECRET_KEY invalidaría también estas credenciales.
    """
    secreto = os.environ.get("EXTERNAL_CREDENTIALS_SECRET") or os.environ.get("JWT_SECRET_KEY", "")
    clave = base64.urlsafe_b64encode(hashlib.sha256(secreto.encode("utf-8")).digest())
    return Fernet(clave)


def cifrar(texto_plano: str) -> str:
    return _fernet().encrypt(texto_plano.encode("utf-8")).decode("utf-8")


def descifrar(texto_cifrado: str) -> str | None:
    try:
        return _fernet().decrypt(texto_cifrado.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("No se pudo descifrar una credencial externa (clave rotada o dato corrupto)")
        return None


def enmascarar(texto_plano_len_hint: int = 4) -> str:
    """Para mostrar en UI sin nunca reenviar la key real al frontend."""
    return "•" * 8 + "…"


TIPOS_VALIDOS = ("nomina",)


def consultar_sistema_externo(conexion: dict, identificador_empleado: str) -> tuple[dict | None, tuple[str, int] | None]:
    """
    Hace el GET al sistema externo usando la conexión ya guardada.
    `conexion["ruta_plantilla"]` es algo como "/api/nomina/{identificador}" —
    se sustituye {identificador} por el valor del campo mapeado del empleado
    (ej. su NumeroEmpleado, o su email, según lo que pida el sistema externo).
    Retorna (datos_json, None) si OK, o (None, (mensaje, status)) si falla —
    nunca lanza: un sistema externo caído no debe tumbar el perfil del empleado.
    """
    api_key = descifrar(conexion.get("api_key_cifrada", ""))
    if not api_key:
        return None, ("No se pudo leer la credencial de esta conexión", 500)

    base_url = (conexion.get("base_url") or "").rstrip("/")
    ruta = (conexion.get("ruta_plantilla") or "/{identificador}").replace(
        "{identificador}", identificador_empleado
    )
    url = f"{base_url}{ruta}"

    headers = {"Authorization": f"{conexion.get('esquema_auth', 'Bearer')} {api_key}"}

    try:
        r = requests.get(url, headers=headers, timeout=conexion.get("timeout", 10))
    except requests.RequestException as e:
        logger.warning("Conexión externa '%s' no respondió: %s", conexion.get("nombre"), e)
        return None, ("El sistema externo no respondió", 503)

    if r.status_code == 404:
        return None, ("Sin información para este empleado en el sistema externo", 404)
    if not r.ok:
        logger.warning("Conexión externa '%s' respondió %s", conexion.get("nombre"), r.status_code)
        return None, (f"El sistema externo respondió con error ({r.status_code})", 502)

    try:
        return r.json(), None
    except ValueError:
        return None, ("El sistema externo no devolvió JSON válido", 502)
