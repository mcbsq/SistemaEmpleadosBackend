# api/usuario/logic.py
#
# CAMBIOS 16-17 abr 2026:
#  [FIX-2]  Validar que password no sea vacío antes de hashear.
#  [FIX-3]  Guardar empleado_id como ObjectId (no como string).
# Integración Aegis: alta/reset de contraseña vía Admin API cuando AEGIS_API_KEY
# está definida; Mongo guarda email + aegis_user_id y no almacena hash.

from flask import jsonify
from bson.objectid import ObjectId
from bson.errors import InvalidId
from werkzeug.security import generate_password_hash
import logging

from core.aegis_config import get_aegis_settings
from core.aegis_client import aegis_admin_create_user, aegis_admin_reset_password


def _serialize(doc):
    """Convierte ObjectId a string para que jsonify pueda serializarlo."""
    if doc is None:
        return None
    doc['_id'] = str(doc['_id'])
    if doc.get('empleado_id') and not isinstance(doc['empleado_id'], str):
        doc['empleado_id'] = str(doc['empleado_id'])
    doc.pop('password', None)
    return doc


def create_usuario(mongo, user, password, empleado_id, role='EMPLOYEE', email=None):
    """
    Alta de usuario de aplicación. Si Aegis admin está activo, la contraseña se
    crea solo en Aegis y en Mongo se guardan email + aegis_user_id (sin campo password).
    Si no, se mantiene el comportamiento anterior (hash en Mongo, regla de 5 caracteres).
    """
    if not user or not user.strip():
        return jsonify({'error': 'El nombre de usuario es obligatorio.'}), 400
    if not password:
        return jsonify({'error': 'La contraseña es obligatoria.'}), 400

    s = get_aegis_settings()
    # Con login Aegis, sin API key no se puede dejar una contraseña solo en Mongo (el login no la usaría).
    if s["login_enabled"] and not s["admin_enabled"]:
        return jsonify({
            'error': 'Alta de usuarios requiere AEGIS_API_KEY cuando el login usa Aegis.',
        }), 503

    email_clean = (email or "").strip().lower()
    if s["admin_enabled"]:
        if not email_clean or "@" not in email_clean:
            return jsonify({'error': 'El correo electrónico es obligatorio para el alta en Aegis.'}), 400
    else:
        if len(password) < 5:
            return jsonify({'error': 'La contraseña debe tener al menos 5 caracteres.'}), 400

    try:
        eid = None
        if empleado_id:
            try:
                eid = ObjectId(empleado_id)
            except (InvalidId, TypeError):
                eid = empleado_id
                logging.warning("empleado_id '%s' no es un ObjectId válido.", empleado_id)

        if s["admin_enabled"]:
            # Primero identidad en Aegis; si falla, no insertamos en Mongo (evita usuarios huérfanos).
            created, err = aegis_admin_create_user(email_clean, password)
            if err:
                body, status = err
                logging.warning("Aegis admin create user falló: %s %s", status, body)
                if isinstance(body, dict):
                    return jsonify(body), status
                return jsonify({'error': 'No se pudo crear el usuario en Aegis'}), 502

            aegis_id = created.get("id") or created.get("user_id")
            if not aegis_id:
                logging.error("Aegis create user sin id en respuesta: %s", created)
                return jsonify({'error': 'Respuesta inválida de Aegis'}), 502

            nuevo = {
                'user':           user.strip(),
                'role':           role,
                'empleado_id':    eid,
                'email':          email_clean,
                'aegis_user_id':  aegis_id,  # enlace estable para /me y reset de contraseña
            }
        else:
            nuevo = {
                'user':        user.strip(),
                'password':    generate_password_hash(password),
                'role':        role,
                'empleado_id': eid,
            }
            if email_clean:
                nuevo['email'] = email_clean

        result = mongo.db.usuario.insert_one(nuevo)
        return jsonify({
            'message': 'Usuario creado',
            '_id':     str(result.inserted_id),
            'user':    user.strip(),
            'role':    role,
        }), 201
    except Exception as e:
        logging.error("Error creando usuario: %s", e)
        return jsonify({'error': str(e)}), 500


def get_usuarios(mongo):
    try:
        docs = list(mongo.db.usuario.find({}))
        return jsonify([_serialize(d) for d in docs]), 200
    except Exception as e:
        logging.error("Error obteniendo usuarios: %s", e)
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
        doc = mongo.db.usuario.find_one({'_id': ObjectId(id)})
        if not doc:
            return jsonify({'error': 'Usuario no encontrado'}), 404

        update = {}
        if user:
            update['user'] = user.strip()
        if role:
            update['role'] = role

        if password:
            s = get_aegis_settings()
            # Contraseña canónica en Aegis si el usuario ya está enlazado; si no, error explícito.
            if s["admin_enabled"] and doc.get("aegis_user_id"):
                err = aegis_admin_reset_password(str(doc["aegis_user_id"]), password)
                if err:
                    body, status = err
                    logging.warning("Aegis reset-password: %s %s", status, body)
                    return jsonify(body) if isinstance(body, dict) else jsonify({'error': str(body)}), status
            elif s["login_enabled"]:
                return jsonify({
                    'error': 'Usuario sin vínculo Aegis; no se puede actualizar la contraseña aquí.',
                }), 400
            else:
                # Modo 100 % legacy: el hash sigue en Mongo.
                if len(password) < 5:
                    return jsonify({'error': 'La contraseña debe tener al menos 5 caracteres.'}), 400
                update['password'] = generate_password_hash(password)

        if not update:
            return jsonify({'error': 'Nada que actualizar'}), 400

        mongo.db.usuario.update_one({'_id': ObjectId(id)}, {'$set': update})
        return jsonify({'message': 'Usuario actualizado'}), 200
    except Exception as e:
        logging.error("Error actualizando usuario: %s", e)
        return jsonify({'error': str(e)}), 500


def delete_usuario(mongo, id):
    try:
        mongo.db.usuario.delete_one({'_id': ObjectId(id)})
        return jsonify({'message': 'Usuario eliminado'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def usuario_existente(mongo, user, email=None):
    """Evita duplicar `user` o el mismo correo cuando se usa campo email (Aegis)."""
    if mongo.db.usuario.find_one({'user': user}):
        return True
    if email and str(email).strip():
        if mongo.db.usuario.find_one({'email': str(email).strip().lower()}):
            return True
    return False
