from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from .logic import login, change_password
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

    @app.route('/recuperar-contrasena', methods=['POST'])
    def recuperar_route():
        from .sesion import solicitar_recuperacion
        ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
        return solicitar_recuperacion(mongo, request.get_json(silent=True) or {}, ip)

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
            return resp
        except Exception as e:
            logging.error(f"Error en ruta de change-password: {str(e)}")
            return jsonify({"error": "Error en el servidor"}), 500
