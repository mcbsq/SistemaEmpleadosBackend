# api/usuario/logic.py
#
# CAMBIOS 16-17 abr 2026:
#  [FIX-2]  Validar que password no sea vacío antes de hashear.
#  [FIX-3]  Guardar empleado_id como ObjectId (no como string).
# Integración Aegis: alta/reset de contraseña vía Admin API cuando AEGIS_API_KEY
# está definida; Mongo guarda email + aegis_user_id y no almacena hash.
#
# CAMBIO (áreas múltiples): areas_administradas es una lista de depto_id,
# solo tiene efecto cuando role == 'ADMIN', y únicamente SUPER_ADMIN puede
# asignarla (ver api/usuario/routes.py). Viaja embebida en el JWT al hacer
# login — ver api/login/logic.py.

from flask import jsonify
from bson.objectid import ObjectId
from bson.errors import InvalidId
from werkzeug.security import generate_password_hash
import logging

from core.aegis_config import get_aegis_settings
from core.aegis_client import (aegis_admin_create_user, aegis_admin_reset_password,
                               aegis_admin_list_users, aegis_admin_set_active)
from core.mailer import send_temp_password_email


def _serialize(doc):
    """Convierte ObjectId a string para que jsonify pueda serializarlo."""
    if doc is None:
        return None
    doc['_id'] = str(doc['_id'])
    if doc.get('empleado_id') and not isinstance(doc['empleado_id'], str):
        doc['empleado_id'] = str(doc['empleado_id'])
    doc.pop('password', None)
    return doc


def _clean_areas(areas_administradas):
    """Normaliza a lista de strings sin duplicados ni vacíos."""
    if not areas_administradas or not isinstance(areas_administradas, list):
        return []
    return sorted({str(a).strip() for a in areas_administradas if str(a).strip()})


def create_usuario(mongo, user, password, empleado_id, role='EMPLOYEE', email=None, areas_administradas=None):
    """
    Alta de usuario de aplicación. Si Aegis admin está activo, Aegis genera una
    contraseña TEMPORAL (el campo password del request se ignora) que se retorna
    como `temp_password` para que el admin la entregue al empleado; este deberá
    cambiarla en su primer inicio de sesión. En Mongo se guardan email +
    aegis_user_id (sin campo password).
    Si no, se mantiene el comportamiento anterior (hash en Mongo, regla de 5 caracteres).

    areas_administradas: ignorado salvo que role == 'ADMIN'. Debe venir de
    una llamada ya protegida con @require_roles('SUPER_ADMIN').
    """
    if not user or not user.strip():
        return jsonify({'error': 'El nombre de usuario es obligatorio.'}), 400

    s = get_aegis_settings()
    if s["login_enabled"] and not s["admin_enabled"]:
        return jsonify({
            'error': 'Alta de usuarios requiere AEGIS_API_KEY cuando el login usa Aegis.',
        }), 503

    email_clean = (email or "").strip().lower()
    if s["admin_enabled"]:
        if not email_clean or "@" not in email_clean:
            return jsonify({'error': 'El correo electrónico es obligatorio para el alta en Aegis.'}), 400
    else:
        if not password:
            return jsonify({'error': 'La contraseña es obligatoria.'}), 400
        if len(password) < 5:
            return jsonify({'error': 'La contraseña debe tener al menos 5 caracteres.'}), 400

    areas = _clean_areas(areas_administradas) if role == 'ADMIN' else []

    try:
        eid = None
        if empleado_id:
            try:
                eid = ObjectId(empleado_id)
            except (InvalidId, TypeError):
                eid = empleado_id
                logging.warning("empleado_id '%s' no es un ObjectId válido.", empleado_id)

        temp_password = None
        if s["admin_enabled"]:
            # Primero identidad en Aegis; si falla, no insertamos en Mongo (evita usuarios huérfanos).
            created, err = aegis_admin_create_user(email_clean)
            if err:
                body, status = err
                logging.warning("Aegis admin create user falló: %s %s", status, body)
                if isinstance(body, dict):
                    return jsonify(body), status
                return jsonify({'error': 'No se pudo crear el usuario en Aegis'}), 502

            aegis_id = created.get("id")
            temp_password = created.get("temp_password")
            if not aegis_id:
                logging.error("Aegis create user sin id en respuesta: %s", created)
                return jsonify({'error': 'Respuesta inválida de Aegis'}), 502

            nuevo = {
                'user':                user.strip(),
                'role':                role,
                'empleado_id':         eid,
                'email':               email_clean,
                'aegis_user_id':       aegis_id,
                'areas_administradas': areas,
            }
        else:
            nuevo = {
                'user':                user.strip(),
                'password':            generate_password_hash(password),
                'role':                role,
                'empleado_id':         eid,
                'areas_administradas': areas,
            }
            if email_clean:
                nuevo['email'] = email_clean

        result = mongo.db.usuario.insert_one(nuevo)
        respuesta = {
            'message':             'Usuario creado',
            '_id':                 str(result.inserted_id),
            'user':                user.strip(),
            'role':                role,
            'areas_administradas': areas,
        }
        if temp_password:
            # La contraseña la generó Aegis. Si hay SMTP configurado se envía
            # al correo del empleado; si no (o si falla), se devuelve en la
            # respuesta para que el admin la entregue en mano.
            if send_temp_password_email(email_clean, user.strip(), temp_password):
                respuesta['email_sent'] = True
                respuesta['message'] = (f'Usuario creado. La contraseña temporal se envió a '
                                        f'{email_clean}; deberá cambiarla al iniciar sesión.')
            else:
                respuesta['temp_password'] = temp_password
                respuesta['message'] = ('Usuario creado. Entrega la contraseña temporal '
                                        'al empleado; deberá cambiarla al iniciar sesión.')
        return jsonify(respuesta), 201
    except Exception as e:
        logging.error("Error creando usuario: %s", e)
        return jsonify({'error': str(e)}), 500


def get_usuarios(mongo):
    try:
        docs = [_serialize(d) for d in mongo.db.usuario.find({})]

        # Enriquecer con el estado real de la identidad en Aegis (is_active,
        # must_change_password). Si Aegis no responde, la lista sale igual
        # pero sin el campo `aegis` — no bloqueamos la pantalla por el IdP.
        s = get_aegis_settings()
        if s["admin_enabled"]:
            aegis_users, err = aegis_admin_list_users()
            if err:
                logging.warning("No se pudo enriquecer usuarios con Aegis: %s", err)
            else:
                por_id = {str(u.get("id")): u for u in aegis_users}
                for d in docs:
                    au = por_id.get(str(d.get("aegis_user_id") or ""))
                    if au:
                        d["aegis"] = {
                            "is_active":            au.get("is_active"),
                            "must_change_password": au.get("must_change_password"),
                        }
                    else:
                        # Sin vínculo o la identidad ya no existe en Aegis:
                        # este usuario no puede iniciar sesión en modo Aegis.
                        d["aegis"] = None

        return jsonify(docs), 200
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


def update_usuario(mongo, id, user=None, password=None, role=None, areas_administradas=None):
    try:
        doc = mongo.db.usuario.find_one({'_id': ObjectId(id)})
        if not doc:
            return jsonify({'error': 'Usuario no encontrado'}), 404

        update = {}
        if user:
            update['user'] = user.strip()
        if role:
            update['role'] = role

        efectivo_role = role or doc.get('role')
        if areas_administradas is not None:
            update['areas_administradas'] = _clean_areas(areas_administradas) if efectivo_role == 'ADMIN' else []
        elif role and role != 'ADMIN' and doc.get('areas_administradas'):
            # Si se le quita el rol ADMIN a alguien, no tiene sentido dejarle áreas asignadas.
            update['areas_administradas'] = []

        temp_password = None
        if password:
            s = get_aegis_settings()
            # Contraseña canónica en Aegis si el usuario ya está enlazado; si no, error explícito.
            # Aegis no acepta contraseña arbitraria: genera una temporal que se
            # devuelve al admin (el valor enviado en `password` se ignora).
            if s["admin_enabled"] and doc.get("aegis_user_id"):
                temp_password, err = aegis_admin_reset_password(str(doc["aegis_user_id"]))
                if err:
                    body, status = err
                    logging.warning("Aegis reset-password: %s %s", status, body)
                    return jsonify(body) if isinstance(body, dict) else jsonify({'error': str(body)}), status
            elif s["login_enabled"]:
                return jsonify({
                    'error': 'Usuario sin vínculo Aegis; no se puede actualizar la contraseña aquí.',
                }), 400
            else:
                if len(password) < 5:
                    return jsonify({'error': 'La contraseña debe tener al menos 5 caracteres.'}), 400
                update['password'] = generate_password_hash(password)

        if not update and not temp_password:
            return jsonify({'error': 'Nada que actualizar'}), 400

        if update:
            mongo.db.usuario.update_one({'_id': ObjectId(id)}, {'$set': update})
        respuesta = {'message': 'Usuario actualizado'}
        if temp_password:
            destino = doc.get('email')
            if destino and send_temp_password_email(destino, doc.get('user', ''), temp_password):
                respuesta['email_sent'] = True
                respuesta['message'] = f'Contraseña temporal generada y enviada a {destino}.'
            else:
                respuesta['temp_password'] = temp_password
                respuesta['message'] = ('Contraseña temporal generada. Entrégala al empleado; '
                                        'deberá cambiarla al iniciar sesión.')
        return jsonify(respuesta), 200
    except Exception as e:
        logging.error("Error actualizando usuario: %s", e)
        return jsonify({'error': str(e)}), 500


def delete_usuario(mongo, id):
    try:
        doc = mongo.db.usuario.find_one({'_id': ObjectId(id)})
        if not doc:
            return jsonify({'error': 'Usuario no encontrado'}), 404

        # Primero desactivar la identidad en Aegis; si el IdP no responde, NO
        # borramos en Mongo para no dejar una identidad huérfana que siga
        # autenticando. Si Aegis ya no la tiene (404), seguimos con el borrado.
        s = get_aegis_settings()
        aegis_id = doc.get('aegis_user_id')
        if s["admin_enabled"] and aegis_id:
            err = aegis_admin_set_active(str(aegis_id), False)
            if err:
                body, status = err
                if status != 404:
                    logging.warning("Aegis set_active=false falló para %s: %s %s", aegis_id, status, body)
                    return jsonify({
                        'error': 'No se pudo desactivar la cuenta en el sistema de identidad; intenta de nuevo.',
                    }), 502

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