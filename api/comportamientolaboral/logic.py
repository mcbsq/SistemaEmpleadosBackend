# api/comportamientolaboral/logic.py
from flask import jsonify, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def _to_object_id(id_str):
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return None


def create_comportamientolaboral(mongo, Fecha, Descripcion, Calificacion, empleado_id=None):
    try:
        doc = {'Fecha': Fecha, 'Descripcion': Descripcion, 'Calificacion': Calificacion}
        if empleado_id:
            eid = _to_object_id(empleado_id)
            if eid is None:
                return jsonify({'error': 'empleado_id inválido'}), 400
            doc['empleado_id'] = eid

        # FIX: antes se guardaba str(insert_one_result) en vez de
        # str(insert_one_result.inserted_id).
        result = mongo.db.comportamientolaboral.insert_one(doc)
        doc['_id'] = str(result.inserted_id)
        if empleado_id:
            doc['empleado_id'] = empleado_id
        return jsonify(doc), 201
    except Exception as e:
        logger.error(f"Error en create_comportamientolaboral: {e}")
        return jsonify({'error': str(e)}), 500


def get_comportamientolaborals(mongo):
    try:
        docs = mongo.db.comportamientolaboral.find()
        return Response(json_util.dumps(docs), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_comportamientolaborals_by_empleado(mongo, empleado_id):
    eid = _to_object_id(empleado_id)
    if eid is None:
        return jsonify({'error': 'empleado_id inválido'}), 400
    try:
        docs = mongo.db.comportamientolaboral.find({'empleado_id': eid})
        return Response(json_util.dumps(docs), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_comportamientolaboral(mongo, id):
    eid = _to_object_id(id)
    if eid is None:
        return jsonify({'error': 'ID inválido'}), 400
    try:
        doc = mongo.db.comportamientolaboral.find_one({'_id': eid})
        if not doc:
            return jsonify({'message': 'Registro no encontrado'}), 404
        return Response(json_util.dumps(doc), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def delete_comportamientolaboral(mongo, id):
    eid = _to_object_id(id)
    if eid is None:
        return jsonify({'error': 'ID inválido'}), 400
    try:
        result = mongo.db.comportamientolaboral.delete_one({'_id': eid})
        if result.deleted_count > 0:
            return jsonify({'message': f'Comportamiento laboral {id} eliminado exitosamente'}), 200
        return jsonify({'message': 'No se encontró el registro para eliminar'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_comportamientolaboral(mongo, _id, Fecha, Descripcion, Calificacion):
    eid = _to_object_id(_id)
    if eid is None:
        return jsonify({'error': 'ID inválido'}), 400
    try:
        mongo.db.comportamientolaboral.update_one(
            {'_id': eid},
            {'$set': {'Fecha': Fecha, 'Descripcion': Descripcion, 'Calificacion': Calificacion}}
        )
        return jsonify({'message': f'Comportamiento laboral {_id} actualizado exitosamente'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500