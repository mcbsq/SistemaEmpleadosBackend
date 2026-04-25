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

            # `identifier` es el nombre del campo en Aegis; `user` es el que ya mandaba el front.
            identifier = (data.get('identifier') or data.get('user') or '').strip()
            password = data.get('password')

            logging.debug("Intento de login (identifier cortado en logs por seguridad)")
            
            return login(mongo, identifier, password)
            
        except Exception as e:
            # Log del error
            logging.error(f"Error en ruta de login: {str(e)}")
            return jsonify({"error": "Error en el servidor"}), 500
