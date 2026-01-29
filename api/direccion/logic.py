from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId

# DIRECCION
def create_direccion(mongo):
    try:
        # Extraemos directamente del JSON enviado por React
        data = request.json
        if not data:
            return jsonify({'message': 'No se recibieron datos'}), 400

        # Mantenemos todos tus campos originales
        calle = data.get('Calle')
        num_ext = data.get('NumExterior')
        num_int = data.get('NumInterior')
        manzana = data.get('Manzana')
        lote = data.get('Lote')
        municipio = data.get('Municipio')
        ciudad = data.get('Ciudad')
        cp = data.get('CodigoP')
        pais = data.get('Pais', 'México') # Default por si no viene
        empleado_id = data.get('empleado_id')

        # Insertar en DB
        # IMPORTANTE: empleado_id se guarda como String o ObjectId según tu preferencia
        # Aquí lo guardamos como lo recibimos para evitar errores de casteo
        id_insertado = mongo.db.direccion.insert_one({
            'Calle': calle,
            'NumExterior': num_ext,
            'NumInterior': num_int,
            'Manzana': manzana,
            'Lote': lote,
            'Municipio': municipio,
            'Ciudad': ciudad,
            'CodigoP': cp,
            'Pais': pais,
            'empleado_id': empleado_id 
        }).inserted_id

        return jsonify({
            '_id': str(id_insertado),
            'message': 'Dirección creada con éxito'
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_direccions(mongo):
    direccions = list(mongo.db.direccion.find())
    return Response(json_util.dumps(direccions), mimetype="application/json")

def get_direccion(mongo, id):
    direccion = mongo.db.direccion.find_one({'_id': ObjectId(id)})
    return Response(json_util.dumps(direccion), mimetype="application/json")

def delete_direccion(mongo, id):
    mongo.db.direccion.delete_one({'_id': ObjectId(id)})
    return jsonify({'message': f'Direccion {id} eliminada'}), 200

def update_direccion(mongo, id):
    data = request.json
    mongo.db.direccion.update_one(
        {'_id': ObjectId(id)},
        {'$set': data}
    )
    return jsonify({'message': 'Actualizado con éxito'}), 200