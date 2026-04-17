# api/usuario/logic.py
from flask import jsonify, request
from bson.objectid import ObjectId
from bson.errors import InvalidId
from werkzeug.security import generate_password_hash
import logging


def _serialize(doc):
    """Convierte ObjectId a string para que jsonify pueda serializarlo."""
    if doc is None:
        return None
    doc['_id'] = str(doc['_id'])
    if doc.get('empleado_id') and not isinstance(doc['empleado_id'], str):
        doc['empleado_id'] = str(doc['empleado_id'])
    # Nunca enviar el hash de contraseña al frontend
    doc.pop('password', None)
    return doc


def create_usuario(mongo, user, password, empleado_id, role='EMPLOYEE'):
    try:
        nuevo = {
            'user':        user,
            'password':    generate_password_hash(password),
            'role':        role,
            'empleado_id': empleado_id,
        }
        result = mongo.db.usuario.insert_one(nuevo)
        return jsonify({
            'message': 'Usuario creado',
            '_id':     str(result.inserted_id),
            'user':    user,
            'role':    role,
        }), 201
    except Exception as e:
        logging.error(f"Error creando usuario: {e}")
        return jsonify({'error': str(e)}), 500


def get_usuarios(mongo):
    try:
        docs = list(mongo.db.usuario.find({}))
        return jsonify([_serialize(d) for d in docs]), 200
    except Exception as e:
        logging.error(f"Error obteniendo usuarios: {e}")
        return jsonify({'error': str(e)}), 500


def get_usuario(mongo, id):
    try:
        doc = mongo.db.usuario.find_one({'_id': ObjectId(id)})
        if not doc:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        return jsonify(_serialize(doc)), 200
    except (InvalidId, Exception) as e:
        return jsonify({'error': str(e)}), 400


def update_usuario(mongo, id, user=None, password=None, role=None):
    try:
        update = {}
        if user:     update['user']     = user
        if password: update['password'] = generate_password_hash(password)
        if role:     update['role']     = role

        if not update:
            return jsonify({'error': 'Nada que actualizar'}), 400

        mongo.db.usuario.update_one({'_id': ObjectId(id)}, {'$set': update})
        return jsonify({'message': 'Usuario actualizado'}), 200
    except Exception as e:
        logging.error(f"Error actualizando usuario: {e}")
        return jsonify({'error': str(e)}), 500


def delete_usuario(mongo, id):
    try:
        mongo.db.usuario.delete_one({'_id': ObjectId(id)})
        return jsonify({'message': 'Usuario eliminado'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def usuario_existente(mongo, user):
    return mongo.db.usuario.find_one({'user': user}) is not None