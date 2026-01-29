from flask import jsonify, request
from werkzeug.security import check_password_hash
from flask_jwt_extended import create_access_token
import logging

#LOGIN

# Función para manejar el proceso de inicio de sesión de los usuarios
def login(mongo, user, password):
    try:
        logging.debug(f"Intento de login - Usuario: {user}")
        
        if not user or not password:
            logging.debug("Falta usuario o contraseña")
            return jsonify({"error": "Falta usuario o contraseña"}), 400

        # Buscar el usuario en la base de datos
        usuario_db = mongo.db.usuario.find_one({'user': user})
        
        if usuario_db:
            logging.debug("Usuario encontrado en la base de datos")
            if check_password_hash(usuario_db['password'], password):
                logging.debug("Contraseña correcta")
                # Crear token con la información del usuario
                access_token = create_access_token(identity={
                    'user': user,
                    'role': usuario_db.get('role', 'USER')
                })
                
                return jsonify({
                    'access_token': access_token,
                    'role': usuario_db.get('role', 'USER'),
                    'message': "Inicio de sesión exitoso"
                }), 200
            else:
                logging.debug("Contraseña incorrecta")
                return jsonify({"error": "Credenciales incorrectas"}), 401
        else:
            logging.debug("Usuario no encontrado")
            return jsonify({"error": "Credenciales incorrectas"}), 401
            
    except Exception as e:
        logging.error(f"Error en login: {str(e)}")
        return jsonify({"error": "Error al conectar con el servidor"}), 500
