from flask import jsonify, request, Blueprint
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from flask import current_app
from pymongo.errors import PyMongoError
from bson.json_util import dumps
import logging

def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

######################################################

# REGISTRO USUARIO
# Función para crear un nuevo usuario en la base de datos
def create_usuario(mongo, user, password, empleado_id):
    # Verifica si el usuario ya existe en la base de datos
    if usuario_existente(mongo, user):
        return jsonify({'error': 'El usuario ya existe en la base de datos. Por favor, elija otro nombre de usuario.'}), 400
    # Intenta obtener el nombre de usuario y la contraseña del cuerpo de la solicitud
    user = request.json['user']
    password = request.json['password']
    empleado_id = request.json['empleado_id']
    # Por defecto, los usuarios creados serán tipo 'USER'
    role = 'USER'

    # Verifica que ambos, usuario y contraseña, hayan sido proporcionados
    if user and password:
        # Genera un hash de la contraseña para almacenamiento seguro
        hashed_password = generate_password_hash(password)
        # Inserta el nuevo usuario en la base de datos con la contraseña hasheada
        result = mongo.db.usuario.insert_one({
            'user': user, 
            'password': hashed_password, 
            'empleado_id': empleado_id,
            'role': role  # Agregamos el campo role
        })
        usuario_id = result.inserted_id
        # Devuelve una respuesta con el ID del usuario creado
        response = jsonify({'_id': str(usuario_id), 'user': user, 'role': role})
        response.status_code = 201
        return response
    else:
        # Si falta el usuario o la contraseña, devuelve un error
        return not_found()

# Función para verificar si el usuario ya existe en la base de datos
def usuario_existente(mongo, user):
    try:
        # Busca un usuario con el nombre dado en la base de datos
        usuario = mongo.db.usuario.find_one({'user': user})
        # Si el usuario existe, retorna True, de lo contrario, retorna False
        return usuario is not None
    except PyMongoError as e:
        # Maneja cualquier error de PyMongo
        current_app.logger.error(f"Error al buscar usuario en la base de datos: {e}")
        return False

# Agregar función para crear super admin
def create_super_admin(mongo):
    super_admin = mongo.db.usuario.find_one({'role': 'SUPER_ADMIN'})
    if not super_admin:
        hashed_password = generate_password_hash('admin123')  # Contraseña por defecto
        mongo.db.usuario.insert_one({
            'user': 'admin',
            'password': hashed_password,
            'role': 'SUPER_ADMIN',
            'empleado_id': None  # El super admin no necesita estar asociado a un empleado
        })
        return True
    return False

#GET
# Función para obtener una lista de todos los usuarios
def get_usuarios(mongo, empleado_id):
    # Recupera todos los usuarios de la base de datos
    usuarios = mongo.db.usuario.find({'empleado_id': ObjectId(empleado_id)})
    # Convierte el resultado a un formato JSON válido.
    response = dumps(usuarios)
    return response

#GET ID
# Función para obtener un usuario específico por su ID
def get_usuario(id, empleado_id, mongo):
    # Encuentra el usuario por su ID en la base de datos.
    usuario = mongo.db.usuario.find_one({'_id': ObjectId(id), 'empleado_id': ObjectId(empleado_id)})
    # Convierte el usuario encontrado a un formato JSON válido.
    response = dumps(usuario)
    return response

#PUT
# Función para actualizar la información de un usuario específico
def update_usuario(id, empleado_id, mongo, user, password):
    # Intenta obtener el nombre de usuario y la contraseña actualizados del cuerpo de la solicitud
    user = request.json['user']
    password = request.json['password']

    # Verifica que se hayan proporcionado tanto el usuario como la contraseña
    if user and password:
        # Prepara la información actualizada del usuario
        usuario = {
            'user': user,
            'password': password
        }

        # Actualiza la información del usuario en la base de datos
        mongo.db.usuario.update_one({'_id': ObjectId(id), 'empleado_id': ObjectId(empleado_id)}, {'$set': usuario})
        # Devuelve una respuesta indicando que la actualización fue exitosa
        response = jsonify({'message': 'Usuario ' + id + ' actualizado exitosamente'})
        response.status_code = 200
        return response
    else:
        # Si falta el usuario o la contraseña, devuelve un error
        return not_found()

#DELETE
# Función para eliminar un usuario específico por su ID
def delete_usuario(id, empleado_id, mongo):
    # Elimina el usuario por su ID de la base de datos
    mongo.db.usuario.delete_one({'_id': ObjectId(id), 'empleado_id': ObjectId(empleado_id)})
    # Devuelve una respuesta indicando que el usuario ha sido eliminado
    response = jsonify({'message': 'Usuario ' + id + ' eliminado exitosamente'})
    response.status_code = 200
    return response

########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response