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
import logging

from core.aegis_config import get_aegis_settings
from core.aegis_client import aegis_password_login, aegis_get_me, aegis_change_password, aegis_resolve_tenant
from core.permissions import PERMISOS_DEFAULT, DASHBOARD_MODULOS, get_permisos_for_role
from core.fechas_especiales import verificar_fechas_especiales
from api.tenants.logic import registrar_tenant

logger = logging.getLogger(__name__)


def _find_usuario_after_aegis(mongo, profile: dict):
    """
    Aegis ya validó la contraseña; aquí enlazamos con datos de negocio (rol, empleado_id).
    Orden: id de Aegis → email guardado en Mongo → user igual a parte local o email completo.
    """
    uid = profile.get("id")
    email_raw = (profile.get("email") or "").strip()
    email = email_raw.lower() if email_raw else ""

    if uid is not None:
        u = mongo.db.usuario.find_one({"aegis_user_id": uid})
        if u:
            return u
        u = mongo.db.usuario.find_one({"aegis_user_id": str(uid)})
        if u:
            return u

    if email:
        u = mongo.db.usuario.find_one({"email": email})
        if u:
            return u
        local = email.split("@", 1)[0]
        u = mongo.db.usuario.find_one({"user": local})
        if u:
            return u
        u = mongo.db.usuario.find_one({"user": email})
        if u:
            return u

    return None


def _issue_token_response(mongo, usuario: dict, login_label: str, must_change_password: bool = False, org_id: str = None):
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

    claims = {
        "user":                user,
        "role":                role,
        "empleado_id":         empleado_id,
        "org_id":              org_id,
        "areas_administradas": areas_administradas,
    }
    access_token = create_access_token(identity=user, additional_claims=claims)

    logger.info("Login exitoso: %s (%s)", user, role)
    verificar_fechas_especiales(mongo)

    return jsonify({
        "access_token":         access_token,
        "user":                 user,
        "role":                 role,
        "empleado_id":          empleado_id,
        "org_id":               org_id,
        "permisos":             permisos,
        "modulos":              modulos,
        "areas_administradas":  areas_administradas,
        "must_change_password": must_change_password,
    }), 200


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


def login(mongo, identifier, password):
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
            # 0) Resolver el tenant dinámicamente (Aegis es multi-tenant: el
            # mismo identifier puede existir en varias empresas). Si no se
            # encuentra bajo la app nueva ("empleados"), se cae al par
            # tenant/app legacy ("cibercom"/"principal") con el que se crearon
            # las cuentas antes de este cambio — así ninguna cuenta existente
            # se rompe mientras se completa la migración.
            tenant_id, app_id = settings["tenant_id"], settings["app_id"]
            resolved, resolve_err = aegis_resolve_tenant(identifier, settings["app_id"])
            if resolved:
                tenant_id, app_id = resolved["tenant_key"], resolved["app_key"]
            elif resolve_err and resolve_err[1] == 409:
                logger.warning("Aegis resolve-tenant ambiguo para identifier=%s", identifier[:3] + "...")
                return jsonify({
                    "error": "Tu cuenta pertenece a más de una empresa. Contacta a soporte para continuar.",
                }), 409
            else:
                # 404 (u otro): probablemente cuenta legacy sin app_permissions
                # nuevas — se reintenta con el par estático de antes.
                tenant_id, app_id = settings["tenant_id"], settings["legacy_app_id"]

            # 1) Autenticar contra Aegis (contraseña vive allí).
            tokens, err = aegis_password_login(identifier, password, tenant_id=tenant_id, app_id=app_id)
            if err:
                body, status = err
                # Transición: opcionalmente reintentar con hash Mongo si Aegis falla.
                if settings["legacy_fallback"] and status in (401, 403, 422):
                    logger.info("Aegis rechazó credenciales; fallback legacy para identifier=%s", identifier[:3] + "...")
                    return _login_legacy(mongo, identifier.strip(), password)
                if status == 401 or status == 403:
                    return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
                if status == 503:
                    if settings["legacy_fallback"]:
                        return _login_legacy(mongo, identifier.strip(), password)
                    return jsonify(body), 503
                logger.warning("Aegis login HTTP %s: %s", status, body)
                return jsonify({"error": "No se pudo iniciar sesión"}), 502

            access_token = tokens.get("access_token")
            if not access_token:
                logger.error("Aegis login sin access_token en respuesta")
                return jsonify({"error": "Error interno del servidor"}), 502

            # 2) Saber email/id canónico en Aegis para buscar la fila en Mongo.
            profile, me_err = aegis_get_me(access_token, tenant_id=tenant_id, app_id=app_id)
            if me_err:
                body, status = me_err
                logger.error("Aegis /v1/me falló: %s %s", status, body)
                return jsonify({"error": "No se pudo validar la sesión"}), 502

            # Multi-tenencia: a partir de aquí toda consulta a Mongo (incluida
            # la búsqueda del usuario que sigue) queda aislada a la empresa
            # que Aegis acaba de resolver — es la autoridad real del tenant,
            # no algo que este backend deba adivinar.
            g.org_id = tenant_id
            usuario = _find_usuario_after_aegis(mongo, profile)
            if not usuario:
                # Auto-aprovisionamiento tipo Notion: si esta empresa (tenant_id)
                # nunca ha tenido NADIE en este sistema, la primera persona que
                # logra loguearse (ya con su cuenta creada del lado de Aegis)
                # se convierte automáticamente en SUPER_ADMIN de su propio
                # espacio aislado — nadie de Cibercom tiene que intervenir a
                # mano. Si la empresa YA tiene gente dada de alta y esta
                # persona no es una de ellas, sigue siendo un 403 (necesita
                # que su propio SUPER_ADMIN la invite).
                if tenant_id != settings["tenant_id"] and mongo.db.usuario.count_documents({}) == 0:
                    email = (profile.get("email") or "").strip().lower()
                    usuario = {
                        "user": email.split("@", 1)[0] if email else f"admin_{tenant_id}",
                        "role": "SUPER_ADMIN",
                        "empleado_id": None,
                        "email": email or None,
                        "aegis_user_id": profile.get("id"),
                        "org_id": tenant_id,
                    }
                    mongo.db.usuario.insert_one(dict(usuario))
                    logger.info(
                        "Auto-aprovisionado primer SUPER_ADMIN de tenant nuevo '%s': %s",
                        tenant_id, usuario["user"],
                    )
                    # Mismo momento en que "nace" la empresa: registrarla en
                    # el catálogo central para que Cibercom la vea (ver
                    # api/tenants/logic.py). resolved trae tenant_name porque
                    # solo se llega aquí cuando resolve-tenant sí encontró un
                    # tenant real (tenant_id != settings["tenant_id"]).
                    registrar_tenant(mongo, tenant_id, nombre=(resolved or {}).get("tenant_name"))
                else:
                    logger.warning(
                        "Login Aegis OK pero sin fila en Mongo (tenant=%s id=%s email=%s)",
                        tenant_id, profile.get("id"), profile.get("email"),
                    )
                    return jsonify({
                        "error": "Usuario no registrado en el sistema de empleados. Contacte al administrador.",
                    }), 403

            # 3) Respuesta idéntica a la histórica: JWT propio + permisos desde
            # Mongo. must_change_password viene de Aegis: True cuando el usuario
            # sigue usando una contraseña temporal generada por el admin.
            return _issue_token_response(
                mongo,
                usuario,
                identifier.strip(),
                must_change_password=bool(tokens.get("must_change_password")),
                org_id=tenant_id,
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

        usuario = mongo.db.usuario.find_one({"user": user})
        if not usuario:
            return jsonify({"error": "Usuario no encontrado"}), 404

        settings = get_aegis_settings()

        if settings["login_enabled"] and usuario.get("aegis_user_id"):
            # Aegis exige mínimo 12 caracteres para la nueva contraseña.
            if len(new_password) < 12:
                return jsonify({"error": "La nueva contraseña debe tener al menos 12 caracteres."}), 400
            identifier = usuario.get("email") or user
            err = aegis_change_password(identifier, current_password, new_password)
            if err:
                body, status = err
                if status in (401, 403):
                    return jsonify({"error": "La contraseña actual es incorrecta"}), 401
                logger.warning("Aegis change-password HTTP %s: %s", status, body)
                if isinstance(body, dict) and body.get("detail"):
                    return jsonify({"error": body["detail"]}), status
                return jsonify({"error": "No se pudo cambiar la contraseña"}), 502
            return jsonify({"message": "Contraseña actualizada"}), 200

        # Modo legacy: hash en Mongo.
        stored = usuario.get("password")
        if not stored or not check_password_hash(stored, current_password):
            return jsonify({"error": "La contraseña actual es incorrecta"}), 401
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