from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId

# POST
def create_catalogodepto(mongo, NombreDepto, Descripcion, Poblacion):
    NombreDepto = request.json.get('NombreDepto')
    Descripcion = request.json.get('Descripcion')
    Poblacion = request.json.get('Poblacion')

    if NombreDepto and Descripcion:
        id_insertado = mongo.db.catalogodepto.insert_one(
            {'NombreDepto': NombreDepto, 'Descripcion': Descripcion, 'Poblacion': Poblacion}
        ).inserted_id
        
        response = jsonify({
            '_id': str(id_insertado),
            'NombreDepto': NombreDepto,
            'Descripcion': Descripcion,
            'Poblacion': Poblacion,
        })
        response.status_code = 201
        return response
    else:
        return not_found()

# GET
def get_catalogodeptos(mongo):
    catalogodeptos = mongo.db.catalogodepto.find()
    response = json_util.dumps(catalogodeptos)
    return Response(response, mimetype="application/json")

# GET ID
def get_catalogodepto(mongo, id):
    catalogodepto = mongo.db.catalogodepto.find_one({'_id': ObjectId(id)})
    response = json_util.dumps(catalogodepto)
    return Response(response, mimetype="application/json")

# DELETE
def delete_catalogodepto(mongo, id):
    mongo.db.catalogodepto.delete_one({'_id': ObjectId(id)})
    return jsonify({'message': f'Departamento {id} eliminado'})

# PUT
def update_catalogodepto(mongo, id, NombreDepto, Descripcion, Poblacion):
    NombreDepto = request.json.get('NombreDepto')
    Descripcion = request.json.get('Descripcion')
    Poblacion = request.json.get('Poblacion')
    
    if NombreDepto:
        mongo.db.catalogodepto.update_one(
            {'_id': ObjectId(id)}, 
            {'$set': {'NombreDepto': NombreDepto, 'Descripcion': Descripcion, 'Poblacion': Poblacion}}
        )
        return jsonify({'message': 'Actualizado exitosamente'})
    return not_found()

def not_found(error=None):
    return jsonify({'message': 'Resource Not Found', 'status': 404}), 404