from flask import jsonify, request
from bson import ObjectId

# Función para guardar o actualizar la jerarquía de empleados en la base de datos
def guardar_jerarquia_logic(mongo, data):
    try:
        # Verifica que los datos recibidos contengan los campos 'name' y 'children'.
        if data and 'name' in data and 'children' in data:
            # Busca una jerarquía existente en la base de datos
            existing_jerarquia = mongo.db.jerarquia_empleados.find_one()
            if existing_jerarquia:
                # Si existe, actualiza la jerarquía existente con los nuevos datos
                mongo.db.jerarquia_empleados.update_one({'_id': existing_jerarquia['_id']}, {'$set': {k: v for k, v in data.items() if k != '_id'}})
                # Retorna una respuesta JSON indicando que la actualización fue exitosa
                return jsonify({"status": "success", "message": "Jerarquía actualizada", "id": str(existing_jerarquia['_id'])})
            else:
                # Si no existe una jerarquía, inserta una nueva
                result = mongo.db.jerarquia_empleados.insert_one(data)
                # Retorna una respuesta JSON indicando que la inserción fue exitosa
                return jsonify({"status": "success", "message": "Jerarquía guardada", "id": str(result.inserted_id)})
        else:
            # Retorna un error si los datos son incorrectos o insuficientes
            return jsonify({"status": "error", "message": "Datos incorrectos"}), 400
    except Exception as e:
        # Retorna un mensaje de error en caso de una excepción
        return jsonify({"status": "error", "message": str(e)}), 500

# Función para obtener la jerarquía de empleados de la base de datos
def obtener_jerarquia_logic(mongo):
    try:
        # Busca la jerarquía en la base de datos
        jerarquia = mongo.db.jerarquia_empleados.find_one()
        if jerarquia:
            # Convierte el ObjectId a string para serialización JSON
            jerarquia['_id'] = str(jerarquia['_id'])
            # Retorna la jerarquía obtenida
            return jsonify({"status": "success", "jerarquia": jerarquia})
        else:
            # Retorna un error si no se encuentra la jerarquía
            return jsonify({"status": "error", "message": "Jerarquía no encontrada"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response