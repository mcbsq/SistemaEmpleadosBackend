from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from .logic import login, change_password
from core.client_ip import ip_cliente
from core.cookies_sesion import limpiar
from core.sesiones import obtener, revocar
import logging

# Esta función configura las rutas relacionadas con las operaciones de inicio de sesión.
def setup_login_routes(app, mongo):
    # Define la ruta '/login' que acepta solicitudes POST para iniciar sesión.
    @app.route('/login', methods=['POST'])
    def login_route():
        try:
            data = request.get_json()

            user = data.get('user')
            password = data.get('password')

            # Log de intento de login (sin registrar la contraseña)
            logging.debug(f"Intento de login recibido para usuario: {user}")

            # Llamar a la función de login
            return login(mongo, user, password, requested_org_id=data.get('org_id'))

        except Exception as e:
            # Log del error
            logging.error(f"Error en ruta de login: {str(e)}")
            return jsonify({"error": "Error en el servidor"}), 500

    # Sesión deslizante: cambia un token vigente por uno nuevo (ver sesion.py).
    @app.route('/refresh', methods=['POST'])
    @jwt_required()
    def refresh_route():
        from .sesion import renovar
        from .logic import _issue_token_response
        return renovar(mongo, get_jwt(), _issue_token_response)

    @app.route('/session', methods=['GET'])
    def session_route():
        sesion = obtener(mongo, request.cookies.get("empleados_sid"))
        if not sesion:
            return jsonify({"error": "Sin sesión"}), 401
        return jsonify({
            "csrf_token": sesion.get("csrf"),
            "session_expires_at": sesion.get("expira_en"),
            "must_change_password": bool(sesion.get("must_change_password")),
        }), 200

    @app.route('/logout', methods=['POST'])
    @jwt_required(optional=True)
    def logout_route():
        from core.aegis_client import aegis_logout
        claims = {}
        try:
            claims = get_jwt() or {}
        except Exception:
            claims = {}
        sid = request.cookies.get("empleados_sid") or claims.get("sid")
        sesion = obtener(mongo, sid)
        if sesion and sesion.get("refresh_token"):
            err = aegis_logout(sesion["refresh_token"], tenant_id=sesion.get("org_id"))
            if err and err[1] >= 500:
                return jsonify({"error": "No se pudo cerrar la sesión de identidad. Vuelve a intentarlo."}), 502
        if sid:
            revocar(mongo, sid)
        respuesta = jsonify({"message": "Sesión cerrada"})
        limpiar(respuesta)
        return respuesta, 200

    # "¿Olvidaste tu contraseña?" con código por correo (ver recuperacion.py).
    @app.route('/recuperar/codigo', methods=['POST'])
    def recuperar_codigo_route():
        from .recuperacion import solicitar_codigo
        return solicitar_codigo(mongo, request.get_json(silent=True) or {}, ip_cliente(request))

    @app.route('/recuperar/verificar', methods=['POST'])
    def recuperar_verificar_route():
        from .recuperacion import verificar_codigo
        return verificar_codigo(mongo, request.get_json(silent=True) or {})

    @app.route('/recuperar/confirmar', methods=['POST'])
    def recuperar_confirmar_route():
        from .recuperacion import confirmar
        return confirmar(mongo, request.get_json(silent=True) or {})

    # Flujo anterior (Aegis manda un enlace); lo sigue usando la app móvil.
    @app.route('/recuperar-contrasena', methods=['POST'])
    def recuperar_route():
        from .sesion import solicitar_recuperacion
        return solicitar_recuperacion(mongo, request.get_json(silent=True) or {}, ip_cliente(request))

    # Cambio de contraseña del propio usuario autenticado. En modo Aegis el
    # cambio ocurre allá (y limpia must_change_password); en legacy, en Mongo.
    @app.route('/change-password', methods=['POST'])
    @jwt_required()
    def change_password_route():
        try:
            data = request.get_json() or {}
            claims = get_jwt()
            resp = change_password(mongo, claims, data.get('current_password'), data.get('new_password'))
            status = resp[1] if isinstance(resp, tuple) else getattr(resp, 'status_code', 200)
            if status == 200:
                # Contraseña nueva = todos los celulares vuelven a pedir login.
                from api.dispositivos.logic import revocar_de_usuario
                revocar_de_usuario(mongo, claims.get('user'), claims.get('org_id'), 'cambio de contraseña')
                if isinstance(resp, tuple):
                    cuerpo, codigo = resp
                    limpiar(cuerpo)
                    return cuerpo, codigo
                limpiar(resp)
            return resp
        except Exception as e:
            logging.error(f"Error en ruta de change-password: {str(e)}")
            return jsonify({"error": "Error en el servidor"}), 500
