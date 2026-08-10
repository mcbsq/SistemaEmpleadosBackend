from flask import jsonify, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId


def create_catalogodepto(mongo, NombreDepto, Descripcion, Poblacion, DeptoPadre=None):
    """
    DeptoPadre: NombreDepto del área de la que depende esta (o None/"" si es
    de primer nivel, ej. Dirección General). Define la jerarquía real que
    usa el Organigrama para dibujar el árbol — antes todas las áreas eran
    hermanas directas de la empresa, sin importar quién reporta a quién.
    """
    id_insertado = mongo.db.catalogodepto.insert_one(
        {'NombreDepto': NombreDepto, 'Descripcion': Descripcion, 'Poblacion': Poblacion,
         'DeptoPadre': (DeptoPadre or None)}
    ).inserted_id

    return jsonify({
        '_id': str(id_insertado),
        'NombreDepto': NombreDepto,
        'Descripcion': Descripcion,
        'Poblacion': Poblacion,
        'DeptoPadre': (DeptoPadre or None),
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


def update_catalogodepto(mongo, id, NombreDepto, Descripcion, Poblacion, DeptoPadre=None):
    try:
        obj_id = ObjectId(id)
    except (InvalidId, TypeError):
        return jsonify({'error': 'ID inválido'}), 400
    if DeptoPadre == NombreDepto:
        return jsonify({'error': 'Un departamento no puede ser su propio padre'}), 400
    mongo.db.catalogodepto.update_one(
        {'_id': obj_id},
        {'$set': {'NombreDepto': NombreDepto, 'Descripcion': Descripcion, 'Poblacion': Poblacion,
                   'DeptoPadre': (DeptoPadre or None)}}
    )
    return jsonify({'message': 'Actualizado exitosamente'}), 200