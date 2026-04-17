# api/educacion/logic.py
from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def _serialize_educacion(doc):
    return {
        "_id":        str(doc["_id"]),
        "empleado_id": str(doc["empleado_id"]),
        "Descripcion": doc.get("Descripcion", ""),
        "Educacion":   doc.get("Educacion", []),
        "Experiencia": doc.get("Experiencia", []),
        "Habilidades": doc.get("Habilidades", {}),
    }


def create_educacion(mongo, empleado_id, data):
    data = request.json
    empleado_id = data.get('empleado_id')

    if not empleado_id:
        return jsonify({'message': 'Falta el ID del empleado'}), 400

    try:
        educacion  = [{'Fecha': e.get('Fecha'), 'Titulo': e.get('Titulo'), 'Descripcion': e.get('Descripcion')} for e in data.get('Educacion', [])]
        experiencia = [{'Fecha': e.get('Fecha'), 'Titulo': e.get('Titulo'), 'Descripcion': e.get('Descripcion')} for e in data.get('Experiencia', [])]

        result = mongo.db.educacion.insert_one({
            'empleado_id': ObjectId(empleado_id),
            'Descripcion': data.get('Descripcion', ''),
            'Educacion':   educacion,
            'Experiencia': experiencia,
            'Habilidades': data.get('Habilidades', {}),
        })

        return jsonify({'_id': str(result.inserted_id), 'message': 'Educación creada'}), 201

    except Exception as e:
        logger.error(f"Error en create_educacion: {e}")
        return jsonify({'error': str(e)}), 500


def get_educacion(mongo):
    try:
        docs = list(mongo.db.educacion.find())
        empleados = {str(e['_id']): f"{e.get('Nombre','')} {e.get('ApelPaterno','')} {e.get('ApelMaterno','')}"
                     for e in mongo.db.empleados.find()}
        result = []
        for d in docs:
            s = _serialize_educacion(d)
            s['NombreCompleto'] = empleados.get(str(d['empleado_id']), '')
            result.append(s)
        return Response(json_util.dumps(result), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_educacion_by_empleado(mongo, empleado_id):
    try:
        doc = mongo.db.educacion.find_one({'empleado_id': ObjectId(empleado_id)})
        if not doc:
            return jsonify({}), 200   # vacío pero no 404 — el perfil usa fallback
        return jsonify(_serialize_educacion(doc)), 200
    except (InvalidId, Exception) as e:
        return jsonify({'error': str(e)}), 500


def delete_educacion(mongo, empleado_id):
    try:
        result = mongo.db.educacion.delete_many({'empleado_id': ObjectId(empleado_id)})
        if result.deleted_count > 0:
            return jsonify({'message': f'Educación eliminada para empleado {empleado_id}'}), 200
        return jsonify({'message': 'No encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_educacion(mongo, empleado_id, data):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    try:
        # empleado_id puede llegar como string o como {"$oid": "..."}
        eid = empleado_id['$oid'] if isinstance(empleado_id, dict) and '$oid' in empleado_id else empleado_id
        result = mongo.db.educacion.update_one(
            {'empleado_id': ObjectId(eid)},
            {'$set': {
                'Descripcion': data.get('Descripcion'),
                'Educacion':   data.get('Educacion'),
                'Experiencia': data.get('Experiencia'),
                'Habilidades': data.get('Habilidades'),
            }}
        )
        if result.matched_count > 0:
            return jsonify({'message': 'Educación actualizada'}), 200
        return jsonify({'message': 'No encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500