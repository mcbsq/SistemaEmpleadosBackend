# api/usuario/logic.py
from flask import jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from bson.json_util import dumps
from pymongo.errors import PyMongoError
from flask import current_app
import logging

ROLES_VALIDOS = {'SUPER_ADMIN', 'ADMIN', 'EMPLOYEE'}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def usuario_existente(mongo, user):
    try:
        return mongo.db.usuario.find_one({'user': user}) is not None
    except PyMongoError as e:
        current_app.logger.error(f"Error buscando usuario: {e}")
        return False

def not_found():
    return jsonify({'message': 'Recurso no encontrado', 'status': 404}), 404

# ─── CREATE ───────────────────────────────────────────────────────────────────
def create_usuario(mongo, user, password, empleado_id):
    if usuario_existente(mongo, user):
        return jsonify({'error': 'El usuario ya existe.'}), 400

    if not user or not password:
        return not_found()

    # El role viene del body — por defecto EMPLOYEE
    # Esto permite crear ADMIN desde el panel de SUPER_ADMIN
    role = request.json.get('role', 'EMPLOYEE')
    if role not in ROLES_VALIDOS:
        role = 'EMPLOYEE'

    hashed_password = generate_password_hash(password)

    result = mongo.db.usuario.insert_one({
        'user':        user,
        'password':    hashed_password,
        'empleado_id': empleado_id,
        'role':        role,
    })

    return jsonify({
        '_id':  str(result.inserted_id),
        'user': user,
        'role': role,
    }), 201

# ─── Crear Super Admin (usada en arranque) ────────────────────────────────────
def create_super_admin(mongo):
    if mongo.db.usuario.find_one({'role': 'SUPER_ADMIN'}):
        return False
    hashed_password = generate_password_hash('admin123')
    mongo.db.usuario.insert_one({
        'user':        'admin',
        'password':    hashed_password,
        'role':        'SUPER_ADMIN',
        'empleado_id': None,
    })
    logging.info("Super Admin 'admin' creado.")
    return True

# ─── GET todos ────────────────────────────────────────────────────────────────
def get_usuarios(mongo):
    usuarios = mongo.db.usuario.find()
    return dumps(usuarios), 200

# ─── GET por ID ───────────────────────────────────────────────────────────────
def get_usuario(mongo, id):
    usuario = mongo.db.usuario.find_one({'_id': ObjectId(id)})
    if not usuario:
        return not_found()
    return dumps(usuario), 200

# ─── PUT ──────────────────────────────────────────────────────────────────────
def update_usuario(mongo, id, user, password):
    if not user or not password:
        return not_found()
    hashed_password = generate_password_hash(password)
    mongo.db.usuario.update_one(
        {'_id': ObjectId(id)},
        {'$set': {'user': user, 'password': hashed_password}}
    )
    return jsonify({'message': f'Usuario {id} actualizado'}), 200

# ─── DELETE ───────────────────────────────────────────────────────────────────
def delete_usuario(mongo, id):
    mongo.db.usuario.delete_one({'_id': ObjectId(id)})
    return jsonify({'message': f'Usuario {id} eliminado'}), 200