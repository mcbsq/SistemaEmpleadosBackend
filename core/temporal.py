# core/temporal.py
# ─────────────────────────────────────────────────────────────────────────────
# Contraseña temporal de una cuenta (la que genera Aegis al darla de alta o al
# restablecerla). RH y el Administrador general pueden volver a consultarla
# en Cuentas MIENTRAS la persona no la cambie: se guarda cifrada en el
# documento de `usuario` y se borra en cuanto define su contraseña.
#
# Llave: TEMP_PASSWORD_KEY (cualquier texto largo) o, si no existe, una
# derivada de JWT_SECRET_KEY. Si la llave cambia, las temporales guardadas
# dejan de poder leerse (se pide restablecer); nunca se exponen en claro.
# ─────────────────────────────────────────────────────────────────────────────
import base64
import hashlib
import logging
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

CAMPOS = ("temp_password_cifrada", "temp_password_generada_en")


def _fernet():
    base = (os.environ.get("TEMP_PASSWORD_KEY") or os.environ.get("JWT_SECRET_KEY") or "").encode()
    if not base:
        raise RuntimeError("Falta TEMP_PASSWORD_KEY / JWT_SECRET_KEY para cifrar temporales")
    llave = base64.urlsafe_b64encode(hashlib.sha256(b"temporal:" + base).digest())
    return Fernet(llave)


def campos_guardar(temp_password):
    """$set para guardar una temporal recién generada."""
    return {
        "temp_password_cifrada": _fernet().encrypt(temp_password.encode()).decode(),
        "temp_password_generada_en": datetime.now(timezone.utc).isoformat(),
    }


def leer(usuario):
    """La temporal en claro, o None si no hay o no se puede descifrar."""
    cifrada = (usuario or {}).get("temp_password_cifrada")
    if not cifrada:
        return None
    try:
        return _fernet().decrypt(cifrada.encode()).decode()
    except (InvalidToken, RuntimeError, ValueError):
        logger.warning("No se pudo descifrar la temporal de %s (¿cambió la llave?)", (usuario or {}).get("user"))
        return None


def olvidar(mongo, filtro):
    """Borra la temporal guardada (la persona ya definió su contraseña)."""
    mongo.db.raw.usuario.update_many(filtro, {"$unset": {c: "" for c in CAMPOS}})
