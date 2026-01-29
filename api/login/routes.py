from flask import request, jsonify
from .logic import login
import logging

# Esta función configura las rutas relacionadas con las operaciones de inicio de sesión.
def setup_login_routes(app, mongo):
    # Define la ruta '/login' que acepta solicitudes POST para iniciar sesión.
    @app.route('/login', methods=['POST'])
    def login_route():
        try:
            data = request.get_json()
            logging.debug(f"Datos recibidos en /login: {data}")
            
            user = data.get('user')
            password = data.get('password')
            
            # Log de intento de login
            logging.debug(f"Intento de login recibido para usuario: {user}")
            
            # Llamar a la función de login
            return login(mongo, user, password)
            
        except Exception as e:
            # Log del error
            logging.error(f"Error en ruta de login: {str(e)}")
            return jsonify({"error": "Error en el servidor"}), 500
