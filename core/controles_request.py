# Controles de la petición: la empresa sale de la sesión, no de un header
# o cuerpo del cliente. must_change_password solo deja cambiar la contraseña
# o cerrar sesión. La caché de acceso no alarga una sesión que Aegis ya
# rechazó en /refresh o /logout.
#
# Las rutas públicas son una lista exacta. Un prefijo amplio no convierte
# en público el resto de la API. /api/v1 usa API key, no cookie de persona.
import os
from datetime import datetime, timezone

from flask import g, jsonify, request

from core.perfiles_aegis import APP_KEY, clasificar_perfiles, misma_empresa_y_app
from core.rol_efectivo import acotar
from core.sesiones import acceso_en_cache, fijar_rol, marcar_acceso, obtener, revocar

_PUBLICAS = {
    ("POST", "/login"),
    ("POST", "/recuperar-contrasena"),
    ("GET", "/health"),
    ("GET", "/session"),
    ("POST", "/public/access-requests"),
    ("GET", "/public/tenants/slug-availability"),
    ("POST", "/public/tenants/register"),
    ("POST", "/public/leads"),
    ("POST", "/login/dispositivo"),
    ("POST", "/monitor/incidents"),
}
_CON_CLAVE = ("/change-password", "/logout", "/refresh")


def _publica(ruta, metodo):
    if (metodo, ruta) in _PUBLICAS:
        return True
    if metodo == "GET" and ruta.startswith("/org/") and ruta.endswith("/config") and ruta.count("/") == 3:
        return True
    # Otro programa entra con API key. La ruta valida esa clave; no es sesión de navegador.
    if ruta.startswith("/api/v1/"):
        return True
    return False


def _origen_permitido():
    crudo = (os.environ.get("CORS_ALLOWED_ORIGINS") or "").strip()
    if not crudo or crudo == "*":
        return None
    permitidos = {o.strip().rstrip("/") for o in crudo.split(",") if o.strip()}
    origen = (request.headers.get("Origin") or "").rstrip("/")
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and origen and origen not in permitidos:
        return jsonify({"error": "Origen no permitido."}), 403
    return None


def _csrf_si_cookie():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if not request.cookies.get("empleados_sid"):
        return None
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return None
    sesion = obtener_de_g()
    if not sesion:
        return jsonify({"error": "Sesión no válida."}), 401
    if request.headers.get("X-CSRF-Token") != sesion.get("csrf"):
        return jsonify({"error": "Falta la verificación de la sesión."}), 403
    return None


def obtener_de_g():
    return getattr(g, "sesion_servidor", None)


def _transitorio(status):
    return status == 429 or status >= 500


def aplicar(mongo, claims):
    """
    claims es el JWT ya verificado o None. Devuelve una respuesta de error
    o None si la petición puede seguir.
    """
    if request.method == "OPTIONS":
        return None
    ruta = request.path or ""
    # El origen se revisa también en el login. Un 403 aquí no es solo CORS.
    origen = _origen_permitido()
    if origen:
        return origen
    if _publica(ruta, request.method):
        return None

    from core.aegis_config import get_aegis_settings
    aegis = bool(get_aegis_settings().get("login_enabled"))
    sid = request.cookies.get("empleados_sid") or (claims or {}).get("sid")
    sesion = obtener(mongo, sid) if sid else None
    g.sesion_servidor = sesion
    if sid and not sesion:
        if ruta == "/logout":
            return None
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401

    if aegis and claims and not sesion:
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    if not sesion and not claims:
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401

    if sesion:
        g.org_id = sesion.get("org_id")
        g.claims_sesion = sesion.get("claims") or {}
        if aegis and not sesion.get("must_change_password") and not sesion.get("access_token") and not sesion.get("refresh_token"):
            revocar(mongo, sesion["sid"])
            return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
        if sesion.get("must_change_password") and ruta not in _CON_CLAVE:
            return jsonify({"error": "Debes cambiar la contraseña antes de continuar."}), 403
        rechazo = _revalidar_acceso(mongo, sesion, ruta)
        if rechazo:
            return rechazo
    elif claims and claims.get("org_id") and not aegis:
        g.org_id = claims.get("org_id")

    universo = (request.headers.get("X-Universo") or "").strip().lower()
    if universo and universo != (g.org_id or ""):
        from api.tenants.routes import es_operador_plataforma
        identidad = claims if isinstance(claims, dict) else {}
        if sesion and sesion.get("claims"):
            identidad = {**identidad, **sesion["claims"]}
        if es_operador_plataforma(identidad):
            g.org_id = universo
            g.modo_soporte = True
            mongo.db.raw.auditoria.insert_one({
                "org_id": universo,
                "usuario": identidad.get("user"),
                "accion": "soporte_lectura",
                "entidad": "modo_soporte",
                "creado_en": datetime.now(timezone.utc).isoformat(),
                "detalle": "Lectura de otra empresa por un operador de plataforma.",
            })

    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.is_json:
        cuerpo = request.get_json(silent=True) or {}
        pedido = str(cuerpo.get("org_id") or "").strip().lower()
        if pedido and g.org_id and pedido != str(g.org_id).lower() and not getattr(g, "modo_soporte", False):
            if ruta not in ("/login", "/recuperar-contrasena"):
                return jsonify({"error": "No puedes cambiar de empresa en esta sesión."}), 403

    if ruta not in _CON_CLAVE and (sesion or claims):
        g.contexto_privado = True
        if not g.org_id:
            return jsonify({"error": "Falta el contexto de empresa."}), 403

    return _csrf_si_cookie()


def _revalidar_acceso(mongo, sesion, ruta):
    from core.aegis_config import get_aegis_settings
    if not get_aegis_settings()["login_enabled"]:
        return None
    if ruta in _CON_CLAVE or acceso_en_cache(sesion) or sesion.get("must_change_password"):
        return None
    from core.migracion_aegis import es_sesion_legacy
    if es_sesion_legacy(sesion):
        return None
    token = sesion.get("access_token")
    if not token:
        revocar(mongo, sesion["sid"])
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    from core.aegis_client import aegis_get_access
    acceso, err = aegis_get_access(token, tenant_id=sesion.get("org_id"), app_id=APP_KEY)
    if err:
        status = err[1]
        if _transitorio(status):
            return jsonify({"error": "El servicio de identidad no está disponible."}), 503
        revocar(mongo, sesion["sid"])
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    perfil = {
        "tenant_id": sesion.get("aegis_tenant_id"),
        "app_key": APP_KEY,
        "is_active": True,
    }
    if not misma_empresa_y_app(perfil, acceso, APP_KEY) or clasificar_perfiles(acceso.get("roles")) == "denegado":
        revocar(mongo, sesion["sid"])
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    efectivo = acotar(sesion.get("rol_local") or (sesion.get("claims") or {}).get("role"), acceso.get("roles"))
    if efectivo is None:
        revocar(mongo, sesion["sid"])
        return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
    if efectivo != sesion.get("rol_efectivo"):
        fijar_rol(mongo, sesion, efectivo)
    marcar_acceso(mongo, sesion["sid"])
    return None
