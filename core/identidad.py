# Identidad que la petición puede usar. El JWT firmado no se reescribe:
# si Aegis ya bajó el perfil, el rol, las áreas y la marca de plataforma
# salen de la sesión de servidor.
import sys

from flask import g, has_request_context

_original = None
_envoltura = None


def identidad_de(identity=None):
    """Copia la identidad y le aplica el tope guardado en la sesión."""
    base = dict(identity) if isinstance(identity, dict) else {}
    if not has_request_context():
        return base
    sesion = getattr(g, "sesion_servidor", None)
    if not isinstance(sesion, dict):
        return base
    rol = sesion.get("rol_efectivo")
    if not rol:
        return base
    claims = sesion.get("claims") or {}
    base["role"] = rol
    if rol == "SUPER_ADMIN":
        base["plataforma"] = bool(claims.get("plataforma"))
    else:
        base["plataforma"] = False
    if rol == "ADMIN":
        areas = claims.get("areas_administradas")
        base["areas_administradas"] = list(areas) if isinstance(areas, list) else []
    else:
        base["areas_administradas"] = []
    return base


def instalar():
    """get_jwt() pasa a devolver la identidad efectiva en todo el proceso."""
    global _original, _envoltura
    import flask_jwt_extended as jwt_ext

    if _original is None:
        _original = jwt_ext.get_jwt

    def get_jwt(*args, **kwargs):
        return identidad_de(_original(*args, **kwargs))

    _envoltura = get_jwt
    jwt_ext.get_jwt = get_jwt
    for mod in list(sys.modules.values()):
        if mod is None:
            continue
        actual = getattr(mod, "get_jwt", None)
        if actual is _original:
            setattr(mod, "get_jwt", get_jwt)
