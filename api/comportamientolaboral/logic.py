from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId


def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

######################################################

#COMPORTAMIENTO LABORAL

# POST
def create_comportamientolaboral(mongo, Fecha, Descripcion, Calificacion):
    # Recibe los datos del cuerpo de la solicitud HTTP
    Fecha = request.json['Fecha']
    Descripcion = request.json['Descripcion']
    Calificacion = request.json['Calificacion']

    if Fecha and Descripcion and Calificacion:
        # Inserta un nuevo comportamiento laboral en la base de datos
        id = mongo.db.comportamientolaboral.insert_one(
            {'Fecha': Fecha, 'Descripcion': Descripcion, 'Calificacion': Calificacion})
        # Crea una respuesta JSON con los datos del comportamiento laboral creado
        response = jsonify({
            '_id': str(id),
            'Fecha': Fecha,
            'Descripcion': Descripcion,
            'Calificacion': Calificacion
        })
        response.status_code = 201 # Establecer el código de estado HTTP 201 (Created)
        return response
    else:
        return not_found() # Llamar a la función not_found() en caso de error

# GET
def get_comportamientolaborals(mongo):
    # Obtiene todos los comportamientos laborales de la base de datos
    comportamientolaborals = mongo.db.comportamientolaboral.find()
    # Convierte los documentos a formato JSON
    response = json_util.dumps(comportamientolaborals)
    return Response(response, mimetype="application/json") # Enviar la respuesta JSON

# GET ID
def get_comportamientolaboral(mongo, id):
    # Busca un comportamiento laboral específico por su ID en la base de datos
    print(id)
    comportamientolaboral = mongo.db.comportamientolaboral.find_one({'_id': ObjectId(id), })
    response = json_util.dumps(comportamientolaboral)
    return Response(response, mimetype="application/json")

# DELETE
def delete_comportamientolaboral(mongo, id):
    # Elimina un comportamiento laboral por su ID de la base de datos
    mongo.db.comportamientolaboral.delete_one({'_id': ObjectId(id)})
    # Crea una respuesta JSON indicando que el comportamiento laboral ha sido eliminado
    response = jsonify({'message': 'comportamientolaboral' + id + ' Deleted Successfully'})
    response.status_code = 200 # Establecer el código de estado HTTP 200 (OK)
    return response


def update_comportamientolaboral(mongo, _id, Fecha, Descripcion, Calificacion):
    # Recibe los nuevos datos del cuerpo de la solicitud HTTP
    Fecha = request.json['Fecha']
    Descripcion = request.json['Descripcion']
    Calificacion = request.json['Calificacion']
    if Fecha and Descripcion and Calificacion:
        # Actualiza un comportamiento laboral por su ID en la base de datos
        mongo.db.comportamientolaboral.update_one(
            {'_id': ObjectId(_id['$oid']) if '$oid' in _id else ObjectId(_id)}, {'$set': {'Fecha': Fecha, 'Descripcion': Descripcion, 'Calificacion': Calificacion}})
        # Crea una respuesta JSON indicando que el comportamiento laboral ha sido actualizado
        response = jsonify({'message': 'comportamientolaboral' + _id + 'Updated Successfuly'})
        response.status_code = 200
        return response
    else:
      return not_found() # Llama a la función not_found() en caso de error
    
########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response