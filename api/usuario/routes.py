from flask import request, jsonify
from .logic import (create_usuario, get_usuarios, get_usuario, delete_usuario, update_usuario, usuario_existente)
import logging
from functools import wraps
from flask_jwt_extended import get_jwt_identity, jwt_required

# Configurar la configuración de registro 
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def require_super_admin(f):
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        current_user = get_jwt_identity()
        if isinstance(current_user, dict) and current_user.get('role') == 'SUPER_ADMIN':
            return f(*args, **kwargs)
        return jsonify({"error": "Acceso no autorizado"}), 403
    return decorated_function

def setup_usuario_routes(app, mongo):
    # Ruta para crear un nuevo usuario
    @app.route('/usuario', methods=['POST'])
    def create_usuario_route():
        # Extrae el nombre de usuario y la contraseña de la solicitud
        user = request.json.get('user')
        password = request.json.get('password')
        empleado_id = request.json.get('empleado_id')

        # Log para verificar que se están recibiendo los datos correctamente
        logging.debug(f"Nombre de usuario recibido: {user}, Contraseña recibida: {password}")

        # Verificar si el usuario ya existe
        if usuario_existente(mongo, user):
            logging.debug(f"El usuario '{user}' ya existe en la base de datos.")
            return jsonify({'error': 'El usuario ya existe en la base de datos. Por favor, elija otro nombre de usuario.'}), 400

        # Si el usuario no existe, llamar a la función de lógica para crear el usuario y devolver la respuesta
        return create_usuario(mongo, user, password, empleado_id)

    # Rutas protegidas solo para super admin
    @app.route('/usuarios', methods=['GET'])
    @require_super_admin
    def get_usuarios_route():
        return get_usuarios(mongo)

    # Ruta para obtener un usuario específico por su ID
    @app.route('/usuario/<id>', methods=['GET'])
    def get_usuario_route(id):
        # Llama a la función de lógica para obtener un usuario por su ID y devuelve la respuesta
        return get_usuario(mongo, id)

    # Ruta para actualizar un usuario específico por su ID
    @app.route('/usuario/<id>', methods=['PUT'])
    def update_usuario_route(id):
        # Extrae el nombre de usuario y la contraseña actualizados de la solicitud
        user = request.json['user']
        password = request.json['password']
        # Llama a la función de lógica para actualizar el usuario y devuelve la respuesta
        return update_usuario(mongo, id, user, password)

    # Ruta para eliminar un usuario específico por su ID
    @app.route('/usuario/<id>', methods=['DELETE'])
    def delete_usuario_route(id):
        # Llama a la función de lógica para eliminar el usuario por su ID y devuelve la respuesta
        return delete_usuario(mongo, id)
