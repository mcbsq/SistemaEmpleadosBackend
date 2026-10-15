# Reglas locales de contraseña nueva. OpenAPI de Aegis (0.1.0) solo fija
# longitud 12–256 en ChangePasswordRequest y PasswordResetConfirmBody.
# El producto exige además mayúscula, minúscula, número y símbolo. Si Aegis
# rechaza por una regla extra, se respeta su respuesta.
import re


def contrasena_aceptable(valor):
    if not isinstance(valor, str) or not (12 <= len(valor) <= 256):
        return False
    return bool(
        re.search(r"[A-Z]", valor)
        and re.search(r"[a-z]", valor)
        and re.search(r"\d", valor)
        and re.search(r"[^A-Za-z0-9]", valor)
    )
