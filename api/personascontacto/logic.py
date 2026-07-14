# api/personascontacto/logic.py
from flask import jsonify, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def create_personascontacto(mongo, personalcontacto):
    if not personalcontacto:
        return jsonify({'error': 'No data provided for personalcontacto'}), 400

    parenstesco       = personalcontacto.get('parenstesco', '')
    nombreContacto    = personalcontacto.get('nombreContacto', '')
    telefonoContacto  = personalcontacto.get('telefonoContacto', '')
    correoContacto    = personalcontacto.get('correoContacto', '')
    direccionContacto = personalcontacto.get('direccionContacto', '')
    empleadoid_str    = personalcontacto.get('empleadoid', '')

    if not parenstesco or not nombreContacto:
        return jsonify({'error': 'parenstesco and nombreContacto are required'}), 400

    try:
        empleadoid = ObjectId(empleadoid_str)
    except (InvalidId, Exception):
        return jsonify({'error': 'Invalid ObjectId for empleadoid'}), 400

    result = mongo.db.personascontacto.insert_one({
        'empleadoid':        empleadoid,
        'parenstesco':       parenstesco,
        'nombreContacto':    nombreContacto,
        'telefonoContacto':  telefonoContacto,
        'correoContacto':    correoContacto,
        'direccionContacto': direccionContacto,
    })

    return jsonify({
        '_id':               str(result.inserted_id),
        'empleadoid':        str(empleadoid),
        'parenstesco':       parenstesco,
        'nombreContacto':    nombreContacto,
        'telefonoContacto':  telefonoContacto,
        'correoContacto':    correoContacto,
        'direccionContacto': direccionContacto,
    }), 201


def get_personascontactos(mongo):
    try:
        docs = list(mongo.db.personascontacto.find())
        empleados = {str(e['_id']): f"{e.get('Nombre','')} {e.get('ApelPaterno','')} {e.get('ApelMaterno','')}"
                     for e in mongo.db.empleados.find()}
        for d in docs:
            d['NombreCompleto'] = empleados.get(str(d.get('empleadoid', '')), '')
        return Response(json_util.dumps(docs), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_personascontacto_by_empleado(mongo, empleadoid):
    try:
        docs = list(mongo.db.personascontacto.find({'empleadoid': ObjectId(empleadoid)}))
        result = [{
            '_id':               str(d['_id']),
            'empleadoid':        str(d['empleadoid']),
            'parenstesco':       d.get('parenstesco', ''),
            'nombreContacto':    d.get('nombreContacto', ''),
            'telefonoContacto':  d.get('telefonoContacto', ''),
            'correoContacto':    d.get('correoContacto', ''),
            'direccionContacto': d.get('direccionContacto', ''),
        } for d in docs]
        return jsonify(result), 200   # lista vacía es válida
    except Exception as e:
        return jsonify({'message': str(e)}), 500


def delete_personascontacto(mongo, empleadoid):
    try:
        result = mongo.db.personascontacto.delete_one({'empleadoid': ObjectId(empleadoid)})
        if result.deleted_count > 0:
            return jsonify({'message': f'Contacto {empleadoid} eliminado'}), 200
        return jsonify({'message': 'No encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# FIX: antes esta función releía request.json y buscaba un 'empleadoid'
# DENTRO del body (personalcontacto.empleadoid) para armar el filtro de
# actualización, ignorando por completo el <empleadoid> real de la URL.
# Si ambos no coincidían, se actualizaba (o se fallaba en actualizar) el
# contacto equivocado. Ahora usa el empleadoid de la URL, que es lo que
# la ruta /personascontacto/empleado/<empleadoid> promete.
def update_personascontacto_by_empleado(mongo, empleadoid, personal_contacto):
    if not personal_contacto:
        return jsonify({'error': 'No data provided'}), 400

    parenstesco       = personal_contacto.get('parenstesco', '')
    nombre_contacto    = personal_contacto.get('nombreContacto', '')
    telefono_contacto  = personal_contacto.get('telefonoContacto', '')
    correo_contacto    = personal_contacto.get('correoContacto', '')
    direccion_contacto = personal_contacto.get('direccionContacto', '')

    if not parenstesco or not nombre_contacto:
        return jsonify({'error': 'parenstesco and nombreContacto are required'}), 400

    try:
        eid = ObjectId(empleadoid)
    except Exception:
        return jsonify({'error': 'Invalid ObjectId'}), 400

    mongo.db.personascontacto.update_one(
        {'empleadoid': eid},
        {'$set': {
            'parenstesco':       parenstesco,
            'nombreContacto':    nombre_contacto,
            'telefonoContacto':  telefono_contacto,
            'correoContacto':    correo_contacto,
            'direccionContacto': direccion_contacto,
        }}
    )
    return jsonify({'message': f'Contacto actualizado para empleado {empleadoid}'}), 200