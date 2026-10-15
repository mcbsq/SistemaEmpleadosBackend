# Cookies de sesión. El identificador opaco y el JWT local van en HttpOnly,
# sin atributo Domain: quedan en el host del API, no en el dominio padre.
# El CSRF no se lee de document.cookie (el front y el API pueden estar en
# hosts distintos). Viaja en el JSON de login, refresh y GET /session, y el
# navegador lo guarda en memoria.
import os

from flask import request


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def parametros_cookie():
    samesite = (os.environ.get("COOKIE_SAMESITE") or "Lax").strip()
    if samesite not in ("Lax", "Strict", "None"):
        samesite = "Lax"
    seguro = request.is_secure or request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower() == "https"
    if _truthy(os.environ.get("COOKIE_SECURE")) or samesite == "None":
        seguro = True
    return {"secure": seguro, "samesite": samesite, "path": "/"}


def fijar(response, sesion, jwt_token):
    if response is None or not sesion:
        return response
    base = parametros_cookie()
    response.set_cookie(
        "empleados_sid", sesion["sid"], httponly=True, max_age=60 * 60 * 24, **base,
    )
    response.set_cookie(
        "access_token_cookie", jwt_token, httponly=True, max_age=60 * 60 * 24, **base,
    )
    return response


def limpiar(response):
    if response is None:
        return response
    base = parametros_cookie()
    for nombre in ("empleados_sid", "access_token_cookie", "empleados_csrf"):
        response.set_cookie(nombre, "", expires=0, httponly=nombre != "empleados_csrf", **base)
    return response
