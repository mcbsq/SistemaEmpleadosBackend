# api/educacion/logic.py
from flask import jsonify, Response
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
    if not empleado_id:
        return jsonify({'message': 'Falta el ID del empleado'}), 400

    try:
        educacion   = [{'Fecha': e.get('Fecha'), 'Titulo': e.get('Titulo'), 'Descripcion': e.get('Descripcion')} for e in data.get('Educacion', [])]
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
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    try:
        eid = ObjectId(empleado_id)

        # FIX: antes se hacía $set de los 4 campos SIEMPRE, aunque no
        # vinieran en el body — un PUT parcial (solo Descripcion, por
        # ejemplo) borraba Educacion/Experiencia/Habilidades a None.
        # Ahora solo se actualiza lo que realmente vino en el body.
        campos_permitidos = ('Descripcion', 'Educacion', 'Experiencia', 'Habilidades')
        set_data = {campo: data[campo] for campo in campos_permitidos if campo in data}

        if not set_data:
            return jsonify({'error': 'Nada que actualizar'}), 400

        result = mongo.db.educacion.update_one({'empleado_id': eid}, {'$set': set_data})
        if result.matched_count > 0:
            return jsonify({'message': 'Educación actualizada'}), 200
        return jsonify({'message': 'No encontrado'}), 404
    except (InvalidId, Exception) as e:
        return jsonify({'error': str(e)}), 500