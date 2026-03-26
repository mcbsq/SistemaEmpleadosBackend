# api/login/logic.py
from flask import jsonify
from werkzeug.security import check_password_hash
from flask_jwt_extended import create_access_token
from bson.objectid import ObjectId
import logging

def login(mongo, user, password):
    try:
        if not user or not password:
            return jsonify({"error": "Falta usuario o contraseña"}), 400

        usuario_db = mongo.db.usuario.find_one({'user': user})

        if not usuario_db:
            return jsonify({"error": "Credenciales incorrectas"}), 401

        if not check_password_hash(usuario_db['password'], password):
            return jsonify({"error": "Credenciales incorrectas"}), 401

        role       = usuario_db.get('role', 'EMPLOYEE')
        empleado_id = str(usuario_db['empleado_id']) if usuario_db.get('empleado_id') else None
        depto_id    = None

        # Si el usuario tiene empleado_id, buscar su departamento en la colección rh
        if empleado_id:
            rh_doc = mongo.db.rh.find_one({'empleado_id': empleado_id})
            if rh_doc:
                depto_id = str(rh_doc.get('depto_id', '')) or None

        # Crear token JWT con identidad completa
        access_token = create_access_token(identity={
            'user':        user,
            'role':        role,
            'empleado_id': empleado_id,
            'depto_id':    depto_id,
        })

        logging.info(f"Login exitoso: {user} ({role})")

        return jsonify({
            'access_token': access_token,
            'role':         role,
            'empleado_id':  empleado_id,
            'depto_id':     depto_id,
            'message':      'Inicio de sesión exitoso',
        }), 200

    except Exception as e:
        logging.error(f"Error en login: {str(e)}")
        return jsonify({"error": "Error al conectar con el servidor"}), 500