from flask import jsonify, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId


def create_catalogodepto(mongo, NombreDepto, Descripcion, Poblacion):
    id_insertado = mongo.db.catalogodepto.insert_one(
        {'NombreDepto': NombreDepto, 'Descripcion': Descripcion, 'Poblacion': Poblacion}
    ).inserted_id

    return jsonify({
        '_id': str(id_insertado),
        'NombreDepto': NombreDepto,
        'Descripcion': Descripcion,
        'Poblacion': Poblacion,
    }), 201


def get_catalogodeptos(mongo):
    catalogodeptos = mongo.db.catalogodepto.find()
    return Response(json_util.dumps(catalogodeptos), mimetype="application/json")


def get_catalogodepto(mongo, id):
    try:
        obj_id = ObjectId(id)
    except (InvalidId, TypeError):
        return jsonify({'error': 'ID inválido'}), 400
    catalogodepto = mongo.db.catalogodepto.find_one({'_id': obj_id})
    if not catalogodepto:
        return jsonify({'message': 'Departamento no encontrado'}), 404
    return Response(json_util.dumps(catalogodepto), mimetype="application/json")


def delete_catalogodepto(mongo, id):
    try:
        obj_id = ObjectId(id)
    except (InvalidId, TypeError):
        return jsonify({'error': 'ID inválido'}), 400
    mongo.db.catalogodepto.delete_one({'_id': obj_id})
    return jsonify({'message': f'Departamento {id} eliminado'}), 200


def update_catalogodepto(mongo, id, NombreDepto, Descripcion, Poblacion):
    try:
        obj_id = ObjectId(id)
    except (InvalidId, TypeError):
        return jsonify({'error': 'ID inválido'}), 400
    mongo.db.catalogodepto.update_one(
        {'_id': obj_id},
        {'$set': {'NombreDepto': NombreDepto, 'Descripcion': Descripcion, 'Poblacion': Poblacion}}
    )
    return jsonify({'message': 'Actualizado exitosamente'}), 200