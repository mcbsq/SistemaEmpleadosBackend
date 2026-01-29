from flask import jsonify, request, Response
from bson.objectid import ObjectId
from bson import json_util

def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

######################################################

#RED SOCIAL

# Función para crear o actualizar los datos de redes sociales de un empleado
def create_or_update_redsocial(mongo, empleado_id, redes_sociales):
    try:
        # Obtener datos del cuerpo de la solicitud
        data = request.get_json()
        empleado_id = data.get('empleado_id')
        redes_sociales = data.get('RedesSociales', [])

        if empleado_id:
            # Verifica si ya hay datos para este empleado en la colección
            existing_data = mongo.db.redsocial.find_one({'empleado_id': ObjectId(empleado_id)})

            if existing_data:
                # Actualiza el registro existente
                mongo.db.redsocial.update_one(
                    {'empleado_id': ObjectId(empleado_id)},
                    {
                        '$set': {
                            'RedesSociales': redes_sociales
                        }
                    }
                )
            else:
                # Inserta un nuevo registro si no hay datos existentes
                result = mongo.db.redsocial.insert_one({
                    'empleado_id': ObjectId(empleado_id),
                    'RedesSociales': redes_sociales
                })
                print(f'Resultado de la inserción en la base de datos: {result.inserted_id}')

            response = jsonify({
                'empleado_id': empleado_id,
                'message': 'Datos de redes sociales creados o actualizados exitosamente'
            })
            response.status_code = 201
            return response
        else:
            return jsonify({'error': 'Datos insuficientes para crear o actualizar redes sociales'}), 400

    except Exception as e:
        # Imprimir cualquier excepción que pueda ocurrir
        print("Error:", e)
        return jsonify({'message': 'Error al procesar la solicitud'}), 500

# Función para obtener los datos de redes sociales de un empleado por su ID
def get_redessociales_empleado(mongo, empleado_id):
    try:
        empleado_id_obj = ObjectId(empleado_id)
        print("Empleado ID (solicitud):", empleado_id)
        print("Empleado ID (convertido a ObjectId):", empleado_id_obj)

        # Cambié 'redessociales' a 'redsocial' en la siguiente línea
        redes_sociales = mongo.db.redsocial.find({'empleado_id': empleado_id_obj})
        result = list(redes_sociales)

        # Formatear los resultados para la respuesta
        formatted_result = []
        for red_social in result:
            redes_sociales_list = red_social.get('RedesSociales', [])
            redes_sociales_item = {
                '_id': str(red_social['_id']),
                "empleado_id": str(red_social['empleado_id']),
                'RedesSociales': [
                    {
                        'redSocialSeleccionada': red.get('redSocialSeleccionada', ''),
                        'URLRedSocial': red.get('URLRedSocial', ''),
                        'NombreRedSocial': red.get('NombreRedSocial', '')
                    } for red in redes_sociales_list
                ]
            }
            formatted_result.append(redes_sociales_item)


        # Devolver una lista vacía si no hay resultados
        return jsonify(formatted_result if formatted_result else [])
    except Exception as e:
        # Imprimir cualquier excepción que pueda ocurrir
        print("Error:", e)
        return jsonify({'message': 'Error en la consulta de redes sociales'}), 500
    

def obtener_lista_de_empleados(mongo):
    empleados = mongo.db.empleados.find()
    empleados_list = list(empleados)  # Convertir el cursor a una lista de Python
    return empleados_list

# Función para obtener todos los datos de red social (GET)
def get_redsocial(mongo):
    redsocial = mongo.db.redsocial.find()
    redsocial_list = list(redsocial)  # Convertir el cursor a una lista de Python
    
    empleados = obtener_lista_de_empleados(mongo)  # Obtener la lista de empleados
    
    for redsocial in redsocial_list:
        empleado_id = redsocial.get("empleado_id")
        empleado_nombre = None
        for empleado in empleados:
            if str(empleado.get("_id")) == str(empleado_id):
                empleado_nombre = f"{empleado.get('Nombre')} {empleado.get('ApelPaterno')} {empleado.get('ApelMaterno')}"
                break
        
        if empleado_nombre:
            redsocial["NombreCompleto"] = empleado_nombre  # Agregar el nombre completo al dato de contacto
        else:
            redsocial["NombreCompleto"] = ""  # Si no se encuentra el empleado, establecer el nombre completo como una cadena vacía
    
    response = json_util.dumps(redsocial_list)
    return Response(response, mimetype="application/json")

# Función para eliminar los datos de redes sociales de un empleado por su ID
def delete_redsocial(mongo, empleado_id):
    try:
        # Convierte el id a ObjectId
        object_id = ObjectId(empleado_id)
        
        # Realiza la eliminación en la colección redsocial
        result = mongo.db.redsocial.delete_one({'empleado_id': object_id})
        
        if result.deleted_count > 0:
            # Devolver una respuesta indicando éxito en la operación de eliminación
            response = jsonify({'message': 'Red Social ' + empleado_id + ' deleted successfully'})
            response.status_code = 200
        else:
            # Devolver error si no se encuentra el registro
            response = jsonify({'message': 'No Red Social found for id ' + empleado_id})
            response.status_code = 404

    except Exception as e:
        response = jsonify({'error': str(e)})
        response.status_code = 500

    return response

# Función para actualizar los datos de redes sociales de un empleado
def update_redessociales_empleado(mongo, empleado_id, redes_sociales_nuevas):
    try:
        empleado_id_obj = ObjectId(empleado_id)
        data = request.get_json()
        redes_sociales_nuevas = data.get('RedesSociales', [])

        # Verificar si ya existe un registro para este empleado
        existing_data = mongo.db.redsocial.find_one({'empleado_id': empleado_id_obj})

        if existing_data:
            # Si existe, actualizar el registro con la nueva información
      
            mongo.db.redsocial.update_one(
                {'empleado_id': empleado_id_obj},
                {
                    '$set': {
                        'RedesSociales': redes_sociales_nuevas
                    }
                }
            )

            response = jsonify({
                'empleado_id': str(empleado_id_obj),
                'message': 'Datos de redes sociales actualizados exitosamente'
            })
            response.status_code = 200
            return response
        else:
            # Si no existe, crear un nuevo registro
           
            result = mongo.db.redsocial.insert_one({
                'empleado_id': empleado_id_obj,
                'RedesSociales': redes_sociales_nuevas
            })
            print(f'Resultado de la inserción en la base de datos: {result.inserted_id}')

            response = jsonify({
                'empleado_id': str(empleado_id_obj),
                'message': 'Datos de redes sociales creados exitosamente'
            })
            response.status_code = 201
            return response

    except Exception as e:
    
        print("Error:", e)
        return jsonify({'message': 'Error al actualizar redes sociales del empleado'}), 500

########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response