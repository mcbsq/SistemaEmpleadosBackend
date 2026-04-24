# api/usuario/logic.py
#
# CAMBIOS 16-17 abr 2026:
#  [FIX-2]  Validar que password no sea vacío antes de hashear.
#           Si llega vacío, el hash se genera de "" y el login siempre falla.
#  [FIX-3]  Guardar empleado_id como ObjectId (no como string).
#           Aunque login/logic.py ya hace str() al leerlo, guardarlo bien
#           evita inconsistencias en queries futuras.
# ──────────────────────────────────────────────────────────────────────────────

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
    # [FIX-2] Validar campos requeridos antes de tocar la base de datos
    if not user or not user.strip():
        return jsonify({'error': 'El nombre de usuario es obligatorio.'}), 400
    if not password:
        return jsonify({'error': 'La contraseña es obligatoria.'}), 400
    if len(password) < 5:
        return jsonify({'error': 'La contraseña debe tener al menos 5 caracteres.'}), 400

    try:
        # [FIX-3] Convertir empleado_id a ObjectId para consistencia en MongoDB
        eid = None
        if empleado_id:
            try:
                eid = ObjectId(empleado_id)
            except (InvalidId, TypeError):
                # Si no es un ObjectId válido, guardarlo como string
                # (no debería pasar, pero mejor no romper el registro)
                eid = empleado_id
                logging.warning(f"empleado_id '{empleado_id}' no es un ObjectId válido.")

        nuevo = {
            'user':        user.strip(),
            'password':    generate_password_hash(password),
            'role':        role,
            'empleado_id': eid,
        }
        result = mongo.db.usuario.insert_one(nuevo)
        return jsonify({
            'message': 'Usuario creado',
            '_id':     str(result.inserted_id),
            'user':    user.strip(),
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
        if user:     update['user']     = user.strip()
        if role:     update['role']     = role
        # [FIX-2] No hashear si el password está vacío
        if password and len(password) >= 5:
            update['password'] = generate_password_hash(password)

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