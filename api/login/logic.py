# api/login/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Login: modo Aegis (delegar credenciales + obtener perfil /me) o modo legacy
# (hash en Mongo). En modo puente, tras Aegis se emite el mismo JWT local que
# ya consume el resto de la API (permisos/rol siguen saliendo de Mongo).
#
# CAMBIO (áreas múltiples): areas_administradas (lista de depto_id) viaja
# embebida en la identidad del JWT cuando role == 'ADMIN', para que
# empleados/logic.py filtre por área sin consultar Mongo en cada request.
# Se asigna únicamente vía SUPER_ADMIN en POST/PUT /usuario.
# NOTA: si cambias las áreas de un ADMIN con sesión activa, el cambio no se
# refleja hasta que vuelva a iniciar sesión (el JWT viejo conserva las áreas
# con las que se emitió).
# ─────────────────────────────────────────────────────────────────────────────
from flask import jsonify, g
from werkzeug.security import check_password_hash
from flask_jwt_extended import create_access_token
from datetime import timedelta
import json
import logging
import os

from core.aegis_config import get_aegis_settings
from core.aegis_client import (
    aegis_password_login, aegis_get_me, aegis_get_access, aegis_change_password, aegis_resolve_tenant,
)
from core.contrasena import contrasena_aceptable
from core.cookies_sesion import fijar
from core.cliente_nativo import es_cliente_nativo
from core.designacion_admin import designar_si_corresponde
from core.perfiles_aegis import APP_KEY, clasificar_perfiles, misma_empresa_y_app
from core.permissions import PERMISOS_DEFAULT, DASHBOARD_MODULOS, get_permisos_for_role
from core.fechas_especiales import verificar_fechas_especiales
from core.rol_efectivo import acotar
from core.sesiones import crear, obtener, prorrogar, revocar, revocar_usuario
from core.vinculo_identidad import buscar_usuario_por_par, validar_correspondencia
from api.tenants.logic import registrar_tenant
from api.org.logic import get_session_minutes

logger = logging.getLogger(__name__)


def _tenant_overrides():
    """
    Mapeo TEMPORAL identifier→org_id para cuentas que Aegis ve como ambiguas
    (más de un tenant para el mismo identifier) por una duplicación de datos
    del lado de Aegis que todavía no se ha limpiado ahí — nuestra API key no
    tiene alcance de plataforma para desactivar la identidad duplicada
    nosotros mismos (confirmado 2026-09-22: 403 "Platform operator session
    required" incluso con una cuenta SUPER_ADMIN de cibercom).

    Con una entrada aquí, ese identifier se manda DIRECTO al org_id indicado
    sin pasar por resolve-tenant (igual que si hubiera entrado por /<empresa>),
    así que el 409 de ambigüedad nunca ocurre para él, en ningún cliente
    (web/mobile) — no es una solución de UI, es del lado del servidor.

    QUITAR la entrada correspondiente (o toda la variable) en cuanto el
    equipo de Aegis desactive la identidad duplicada — dejarla más tiempo del
    necesario oculta si Aegis se limpia o no.

    Formato en AEGIS_TENANT_OVERRIDES (env var, JSON):
      {"biancamendoza75@yahoo.com.mx": "herramientas-y-moldes-industriales"}
    """
    raw = (os.environ.get("AEGIS_TENANT_OVERRIDES") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k).strip().lower(): str(v).strip().lower() for k, v in data.items()}
    except (ValueError, AttributeError, TypeError):
        logger.error("AEGIS_TENANT_OVERRIDES no es un JSON válido — se ignora.")
        return {}


def _find_usuario_after_aegis(mongo, profile: dict, org_id: str = None):
    """Pareja UUID de empresa + UUID de usuario. No enlaza por correo."""
    return buscar_usuario_por_par(
        mongo,
        profile.get("id"),
        profile.get("tenant_id"),
        org_id or "",
    )


def _detalle_aegis(body):
    if isinstance(body, dict):
        detalle = body.get("detail") or body.get("error") or ""
        if isinstance(detalle, list):
            return " ".join(str(parte) for parte in detalle)
        return str(detalle)
    return str(body or "")


def _pide_cambio(err):
    if not err or not isinstance(err, tuple):
        return False
    body, status = err
    return status == 403 and "password change" in _detalle_aegis(body).lower()


def _issue_token_response(
    mongo, usuario: dict, login_label: str, must_change_password: bool = False,
    org_id: str = None, sesion_aegis: dict = None, sid_existente: str = None,
    rol_local: str = None, incluir_jwt=None,
):
    """
    Emite el access_token de Flask-JWT. El claim "sub" es el username (string,
    exigido por RFC 7519 / validado por PyJWT >= 2.10); el resto de la identidad
    (role, empleado_id, org_id, areas_administradas) va como additional_claims
    y se lee con get_jwt() en vez de get_jwt_identity() en el resto de la API.
    login_label solo ayuda si falta user en el doc.

    org_id: el tenant YA resuelto contra Aegis (autoridad real de a qué
    empresa pertenece este login) tiene prioridad sobre lo que diga el doc de
    Mongo — así una cuenta legacy sin org_id migrado igual queda con el
    tenant correcto en el JWT desde el primer login post-migración.
    """
    # Cuenta desactivada (p. ej. el empleado fue dado de baja): no entra,
    # aunque Aegis todavía acepte su contraseña.
    if usuario.get("activo") is False:
        return jsonify({"error": "Tu cuenta está desactivada. Contacta a Recursos Humanos."}), 403

    user = usuario.get("user") or login_label
    role = usuario.get("role", "EMPLOYEE")
    empleado_id = str(usuario.get("empleado_id") or "")
    org_id = org_id or usuario.get("org_id") or "cibercom"

    # Roles de sistema: tabla fija. Roles personalizados (creados en Gestión
    # de roles): se resuelven en vivo contra roles_custom, para que el login
    # de un rol inventado por el cliente refleje sus permisos reales.
    if role in PERMISOS_DEFAULT:
        permisos = usuario.get("permisos") or PERMISOS_DEFAULT[role]
        modulos = usuario.get("modulos") or DASHBOARD_MODULOS.get(role, DASHBOARD_MODULOS["EMPLOYEE"])
    else:
        permisos = usuario.get("permisos") or get_permisos_for_role(mongo, role) or PERMISOS_DEFAULT["EMPLOYEE"]
        modulos = usuario.get("modulos") or DASHBOARD_MODULOS["EMPLOYEE"]

    # Solo tiene efecto real para ADMIN; SUPER_ADMIN ve todo y EMPLOYEE usa
    # su propia área (resuelta en empleados/logic.py vía su empleado_id).
    areas_administradas = (usuario.get("areas_administradas") or []) if role == "ADMIN" else []
    minutos = get_session_minutes(mongo, org_id)
    # plataforma solo si ya está en la cuenta local. Un perfil admin de
    # producto no la enciende.
    plataforma = bool(usuario.get("plataforma")) and role == "SUPER_ADMIN"
    if incluir_jwt is None:
        incluir_jwt = not get_aegis_settings()["login_enabled"]
    # La app móvil sí recibe el JWT (ligado a la misma sesión del servidor);
    # el navegador no (vive en cookie HttpOnly). Ver core/cliente_nativo.py.
    if es_cliente_nativo():
        incluir_jwt = True

    claims = {
        "plataforma":          plataforma,
        "user":                user,
        "role":                role,
        "empleado_id":         empleado_id,
        "org_id":              org_id,
        "areas_administradas": areas_administradas,
        "must_change_password": bool(must_change_password),
    }
    if sid_existente:
        sesion = prorrogar(mongo, sid_existente, minutos)
        if not sesion:
            return jsonify({"error": "Tu sesión ya no es válida. Inicia sesión de nuevo."}), 401
        if sesion.get("rol_efectivo"):
            role = sesion["rol_efectivo"]
            if role in PERMISOS_DEFAULT:
                permisos = PERMISOS_DEFAULT[role]
                modulos = DASHBOARD_MODULOS.get(role, DASHBOARD_MODULOS["EMPLOYEE"])
            plataforma = bool(sesion.get("claims", {}).get("plataforma")) and role == "SUPER_ADMIN"
            claims["role"] = role
            claims["plataforma"] = plataforma
        claims["sid"] = sid_existente
    else:
        sesion = crear(
            mongo, user=user, org_id=org_id, claims=claims,
            must_change_password=must_change_password,
            aegis=sesion_aegis, minutos=minutos, rol_local=rol_local or role,
        )
        claims["sid"] = sesion["sid"]
    access_token = create_access_token(
        identity=user, additional_claims=claims,
        expires_delta=timedelta(minutes=minutos),
    )

    logger.info("Login exitoso: %s (%s)", user, role)
    verificar_fechas_especiales(mongo)

    cuerpo = {
        "user":                 user,
        "role":                 role,
        "empleado_id":          empleado_id,
        "org_id":               org_id,
        "permisos":             permisos,
        "modulos":              modulos,
        "areas_administradas":  areas_administradas,
        "must_change_password": must_change_password,
        "plataforma":           plataforma,
        "session_expires_at":   sesion.get("expira_en"),
        # La app solo ofrece la llave de dispositivo (huella) si el backend
        # la acepta; con Aegis la identidad no se delega a esa llave.
        "dispositivos":         not get_aegis_settings()["login_enabled"],
        "csrf_token":           sesion.get("csrf"),
    }
    if incluir_jwt:
        cuerpo["access_token"] = access_token
    respuesta = jsonify(cuerpo)
    fijar(respuesta, sesion, access_token)
    return respuesta, 200


def _login_legacy(mongo, user, password):
    """Flujo anterior: usuario y hash almacenados solo en Mongo (sin llamar a Aegis)."""
    if not user or not password:
        return jsonify({"error": "Usuario y contraseña son requeridos"}), 400

    # Sin Aegis no hay tenant que resolver — todo lo que vive en modo legacy
    # pertenece al único tenant de este despliegue.
    g.org_id = "cibercom"
    usuario = mongo.db.usuario.find_one({"user": user})
    if not usuario:
        logger.warning("Login fallido — usuario no encontrado: %s", user)
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    stored = usuario.get("password")
    if not stored or not check_password_hash(stored, password):
        logger.warning("Login fallido — contraseña incorrecta: %s", user)
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    return _issue_token_response(mongo, usuario, user)


def login(mongo, identifier, password, requested_org_id=None):
    """
    Punto único de entrada del login HTTP.
    `identifier` = lo que Aegis espera (email completo o parte local); la ruta
    también acepta el campo JSON `user` por compatibilidad con el frontend.
    """
    try:
        if not identifier or not password:
            return jsonify({"error": "Usuario y contraseña son requeridos"}), 400

        settings = get_aegis_settings()

        if settings["login_enabled"]:
            # app_key fijo. Un 404, 409, 429 o 5xx no cambia de aplicación
            # ni consulta el hash de Mongo.
            app_id = APP_KEY
            legacy = False
            resolved = None
            requested_org_id = (requested_org_id or "").strip().lower()
            override_tenant = _tenant_overrides().get((identifier or "").strip().lower())
            if requested_org_id:
                tenant_id = requested_org_id
            elif override_tenant:
                logger.info("Login usando contexto de empresa conocido")
                tenant_id = override_tenant
            else:
                resolved, resolve_err = aegis_resolve_tenant(identifier, app_id)
                if resolve_err:
                    status = resolve_err[1]
                    if status == 409:
                        return jsonify({
                            "error": "Tu cuenta pertenece a más de una empresa. Usa la liga específica de tu empresa.",
                        }), 409
                    if status == 429:
                        return jsonify({"error": "Demasiadas solicitudes. Intenta más tarde."}), 429
                    if status == 404 and settings.get("migracion") and settings.get("tenant_id"):
                        # Cuenta sin la app "empleados" todavía: entra con la app
                        # anterior de la empresa base, como antes de la integración.
                        logger.info("Login en modo migración con la app anterior")
                        tenant_id, app_id, legacy = settings["tenant_id"], settings["legacy_app_id"], True
                    elif status == 404:
                        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
                    elif status >= 500:
                        return jsonify({"error": "Servicio de autenticación no disponible"}), 503
                    else:
                        return jsonify({"error": "No se pudo iniciar sesión"}), 502
                elif (resolved or {}).get("app_key") not in (None, "", app_id):
                    logger.error("resolve-tenant devolvió otra app; no se usa")
                    return jsonify({"error": "No se pudo iniciar sesión"}), 502
                else:
                    tenant_id = resolved["tenant_key"]

            tokens, err = aegis_password_login(identifier, password, tenant_id=tenant_id, app_id=app_id)
            if err:
                _body, status = err
                # 422: Aegis rechazó el formato (p. ej. contraseña demasiado corta);
                # para quien escribe es lo mismo que una contraseña incorrecta.
                if status in (401, 403, 404, 422):
                    return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
                if status == 429:
                    return jsonify({"error": "Demasiadas solicitudes. Intenta más tarde."}), 429
                if status >= 500:
                    return jsonify({"error": "Servicio de autenticación no disponible"}), 503
                return jsonify({"error": "No se pudo iniciar sesión"}), 502

            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            if not access_token or not refresh_token:
                logger.error("Aegis login sin par de tokens")
                return jsonify({"error": "Error interno del servidor"}), 502

            profile, me_err = aegis_get_me(access_token, tenant_id=tenant_id, app_id=app_id)
            if me_err:
                logger.error("Aegis /v1/me falló: %s", me_err[1])
                return jsonify({"error": "No se pudo validar la sesión"}), 502

            debe_cambiar = bool(tokens.get("must_change_password") or profile.get("must_change_password"))
            acceso = None
            if not debe_cambiar and not legacy:
                acceso, acceso_err = aegis_get_access(access_token, tenant_id=tenant_id, app_id=app_id)
                if _pide_cambio(acceso_err):
                    debe_cambiar = True
                elif acceso_err:
                    status = acceso_err[1]
                    if status == 429 or status >= 500:
                        return jsonify({"error": "Servicio de autenticación no disponible"}), 503
                    logger.error("Aegis /v1/access falló: %s", status)
                    return jsonify({"error": "No se pudo validar el acceso"}), 502
                elif not misma_empresa_y_app(profile, acceso, app_id):
                    return jsonify({
                        "error": "El acceso a Empleados no está disponible para esta cuenta.",
                    }), 403
                elif clasificar_perfiles(acceso.get("roles")) == "denegado":
                    return jsonify({"error": "Perfil de acceso no reconocido."}), 403

            if validar_correspondencia(mongo, tenant_id, profile.get("tenant_id"), app_id) == "conflicto":
                return jsonify({
                    "error": "La empresa no coincide con el vínculo ya registrado.",
                }), 409

            g.org_id = tenant_id
            sesion_aegis = {
                "user_id": profile.get("id"),
                "tenant_id": profile.get("tenant_id"),
                "app_key": app_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
            if debe_cambiar:
                usuario = _find_usuario_after_aegis(mongo, profile, org_id=tenant_id)
                if usuario and usuario.get("activo") is False:
                    return jsonify({"error": "Tu cuenta está desactivada. Contacta a Recursos Humanos."}), 403
                if not usuario:
                    usuario = {
                        "user": (profile.get("email") or identifier).strip().lower(),
                        "role": "EMPLOYEE",
                        "plataforma": False,
                        "org_id": tenant_id,
                        "activo": True,
                        "email": profile.get("email"),
                    }
                else:
                    usuario = dict(usuario)
                    usuario["role"] = "EMPLOYEE"
                    usuario["plataforma"] = False
                return _issue_token_response(
                    mongo, usuario, identifier.strip(),
                    must_change_password=True, org_id=tenant_id,
                    sesion_aegis=sesion_aegis, rol_local="EMPLOYEE", incluir_jwt=False,
                )

            usuario = _find_usuario_after_aegis(mongo, profile, org_id=tenant_id)
            if not usuario:
                usuario = designar_si_corresponde(mongo, tenant_id, profile, (acceso or {}).get("roles"))
                if usuario:
                    registrar_tenant(mongo, tenant_id, nombre=(resolved or {}).get("tenant_name"))
                    logger.info("Administrador designado para org_id=%s", tenant_id)
                else:
                    logger.warning("Login Aegis sin vínculo local en org_id=%s", tenant_id)
                    return jsonify({
                        "error": "Usuario no registrado en el sistema de empleados. Contacte al administrador.",
                    }), 403

            rol_local = usuario.get("role")
            # En modo migración (app anterior) el rol es el de Mongo, como antes.
            rol = rol_local if legacy else acotar(rol_local, (acceso or {}).get("roles"))
            if rol is None:
                return jsonify({"error": "Perfil de acceso no reconocido."}), 403
            usuario = dict(usuario)
            usuario["role"] = rol
            return _issue_token_response(
                mongo,
                usuario,
                identifier.strip(),
                must_change_password=False,
                org_id=tenant_id,
                sesion_aegis=sesion_aegis,
                rol_local=rol_local,
                incluir_jwt=False,
            )

        return _login_legacy(mongo, identifier.strip(), password)

    except Exception as e:
        logger.error("Error en login: %s", e)
        return jsonify({"error": "Error interno del servidor"}), 500


def change_password(mongo, jwt_claims, current_password, new_password):
    """
    Cambio de contraseña del propio usuario autenticado (POST /change-password).
    En modo Aegis delega en /v1/auth/change-password (revoca sesiones de refresh
    y limpia must_change_password allá). En modo legacy actualiza el hash en Mongo.
    """
    try:
        if not current_password or not new_password:
            return jsonify({"error": "Contraseña actual y nueva son requeridas"}), 400

        user = jwt_claims.get("user") if isinstance(jwt_claims, dict) else None
        if not user:
            return jsonify({"error": "Sesión inválida"}), 401

        settings = get_aegis_settings()
        sesion = getattr(g, "sesion_servidor", None)
        if settings["login_enabled"] and isinstance(sesion, dict) and sesion.get("must_change_password"):
            if not contrasena_aceptable(new_password):
                return jsonify({
                    "error": "La nueva contraseña debe tener entre 12 y 256 caracteres, "
                             "con mayúscula, minúscula, número y símbolo.",
                }), 400
            identifier = sesion.get("user") or user
            err = aegis_change_password(
                identifier, current_password, new_password,
                tenant_id=sesion.get("org_id"), app_id=APP_KEY,
            )
            if err:
                body, status = err
                if status in (401, 403):
                    return jsonify({"error": "La contraseña que escribiste no es correcta. Si es tu primer ingreso, usa la contraseña temporal que te llegó por correo."}), 401
                logger.warning("Aegis change-password HTTP %s: %s", status, body)
                if isinstance(body, dict) and body.get("detail"):
                    return jsonify({"error": body["detail"]}), status
                return jsonify({"error": "No se pudo cambiar la contraseña"}), 502
            revocar(mongo, sesion.get("sid"))
            revocar_usuario(mongo, identifier, sesion.get("org_id"))
            return jsonify({
                "message": "Contraseña actualizada. Vuelve a iniciar sesión.",
                "reautenticar": True,
            }), 200

        usuario = mongo.db.usuario.find_one({"user": user})
        if not usuario:
            return jsonify({"error": "Usuario no encontrado"}), 404

        settings = get_aegis_settings()

        if settings["login_enabled"] and usuario.get("aegis_user_id"):
            if not contrasena_aceptable(new_password):
                return jsonify({
                    "error": "La nueva contraseña debe tener entre 12 y 256 caracteres, "
                             "con mayúscula, minúscula, número y símbolo.",
                }), 400
            identifier = usuario.get("email") or user
            # org_id en Mongo es el tenant_key que Aegis ya resolvió para
            # esta cuenta (no es ambiguo como en el login genérico — este
            # documento es EL registro de este usuario, sin necesidad de
            # resolve-tenant ni del override temporal de esa función).
            err = aegis_change_password(identifier, current_password, new_password, tenant_id=usuario.get("org_id"))
            if err:
                body, status = err
                if status in (401, 403):
                    return jsonify({"error": "La contraseña que escribiste no es correcta. Si es tu primer ingreso, usa la contraseña temporal que te llegó por correo."}), 401
                logger.warning("Aegis change-password HTTP %s: %s", status, body)
                if isinstance(body, dict) and body.get("detail"):
                    return jsonify({"error": body["detail"]}), status
                return jsonify({"error": "No se pudo cambiar la contraseña"}), 502
            revocar_usuario(mongo, user, usuario.get("org_id"))
            return jsonify({
                "message": "Contraseña actualizada. Vuelve a iniciar sesión.",
                "reautenticar": True,
            }), 200

        # Modo legacy: hash en Mongo.
        stored = usuario.get("password")
        if not stored or not check_password_hash(stored, current_password):
            return jsonify({"error": "La contraseña que escribiste no es correcta. Si es tu primer ingreso, usa la contraseña temporal que te llegó por correo."}), 401
        if len(new_password) < 5:
            return jsonify({"error": "La nueva contraseña debe tener al menos 5 caracteres."}), 400
        from werkzeug.security import generate_password_hash
        mongo.db.usuario.update_one(
            {"_id": usuario["_id"]},
            {"$set": {"password": generate_password_hash(new_password)}},
        )
        return jsonify({"message": "Contraseña actualizada"}), 200

    except Exception as e:
        logger.error("Error en change_password: %s", e)
        return jsonify({"error": "Error interno del servidor"}), 500
