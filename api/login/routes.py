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

    # Cambio de contraseña del propio usuario autenticado. En modo Aegis el
    # cambio ocurre allá (y limpia must_change_password); en legacy, en Mongo.
    @app.route('/change-password', methods=['POST'])
    @jwt_required()
    def change_password_route():
        try:
            data = request.get_json() or {}
            return change_password(
                mongo,
                get_jwt(),
                data.get('current_password'),
                data.get('new_password'),
            )
        except Exception as e:
            logging.error(f"Error en ruta de change-password: {str(e)}")
            return jsonify({"error": "Error en el servidor"}), 500
