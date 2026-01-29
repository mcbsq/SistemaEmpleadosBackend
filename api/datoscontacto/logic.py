from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
import traceback

def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

######################################################

# DATOS CONTACTO
def create_datoscontacto(mongo, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos, empleado_id):
    try:
        # Recibir los datos del cuerpo de la solicitud HTTP
        TelFijo = request.json.get('TelFijo', None)
        TelCelular = request.json.get('TelCelular', None)
        IdWhatsApp = request.json.get('IdWhatsApp', None)
        IdTelegram = request.json.get('IdTelegram', None)
        ListaCorreos = request.json.get('ListaCorreos', None)

        # Insertar en la base de datos
        id = mongo.db.datoscontacto.insert_one({
            'EmpleadoId': ObjectId(empleado_id),
            'TelFijo': TelFijo,
            'TelCelular': TelCelular,
            'IdWhatsApp': IdWhatsApp,
            'IdTelegram': IdTelegram,
            'ListaCorreos': ListaCorreos
        })

        response = jsonify({
            '_id': str(id),
            'EmpleadoId': empleado_id,
            'TelFijo': TelFijo,
            'TelCelular': TelCelular,
            'IdWhatsApp': IdWhatsApp,
            'IdTelegram': IdTelegram,
            'ListaCorreos': ListaCorreos,
        })

        response.status_code = 201  # Establecer el código de estado HTTP 201 (Created)
        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500  # Manejar errores y devolver una respuesta JSON con estado 500 (Internal Server Error)


# Función para obtener datos de contacto por empleado (GET)
def get_datoscontacto_by_empleado(mongo, empleado_id):
    try:
        empleado_object_id = ObjectId(empleado_id)
        datoscontacto = mongo.db.datoscontacto.find_one({'EmpleadoId': empleado_object_id})

        if datoscontacto:
            # Asegúrate de que la estructura de datoscontacto sea como se espera
            datoscontacto_formato = {
                "_id": str(datoscontacto["_id"]),
                "EmpleadoId": str(datoscontacto["EmpleadoId"]),
                "TelFijo": datoscontacto["TelFijo"],
                "TelCelular": datoscontacto["TelCelular"],
                "IdWhatsApp": datoscontacto["IdWhatsApp"],
                "IdTelegram": datoscontacto["IdTelegram"],
                "ListaCorreos": datoscontacto["ListaCorreos"]
            }

            return jsonify(datoscontacto_formato), 200 # Devolver una respuesta JSON con estado 200 (OK)
        else:
            return jsonify({"error": "Datos de contacto no encontrados"}), 404 # Devolver una respuesta JSON con estado 404 (Not Found)

    except Exception as e:
        print("Error en get_datoscontacto_by_empleado:", str(e))
        traceback.print_exc()  # Imprime la traza completa de la excepción
        return jsonify({"error": "Error interno del servidor"}), 500 # Devolver una respuesta JSON con estado 500 (Internal Server Error)

# Función para obtener todos los datos de contacto (GET)
def get_datoscontactos(mongo):
    datoscontactos = mongo.db.datoscontacto.find()
    response = json_util.dumps(datoscontactos)
    return Response(response, mimetype="application/json") # Enviar la respuesta JSON

# Función para eliminar datos de contacto por ID (DELETE)
def delete_datoscontacto(mongo, id):
    try:
        # Convierte el id a ObjectId
        object_id = ObjectId(id)
        # Realiza la eliminación
        result = mongo.db.datoscontacto.delete_one({'EmpleadoId': object_id})
        if result.deleted_count > 0:
            response = jsonify({'message': 'datoscontacto ' + id + ' deleted successfully'})
            response.status_code = 200 # Establecer el código de estado HTTP 200 (OK)
        else:
            response = jsonify({'message': 'datoscontacto ' + id + ' not found'})
            response.status_code = 404 # Establecer el código de estado HTTP 404 (Not Found)
    except Exception as e:
        response = jsonify({'error': str(e)})
        response.status_code = 500 # Establecer el código de estado HTTP 500 (Internal Server Error)
    return response

# Función para actualizar datos de contacto por ID (PUT)
def update_datoscontacto(mongo, empleado_id, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos):
    try:
        # Recibir los nuevos datos del cuerpo de la solicitud HTTP
        TelFijo = request.json.get('TelFijo', None)
        TelCelular = request.json.get('TelCelular', None)
        IdWhatsApp = request.json.get('IdWhatsApp', None)
        IdTelegram = request.json.get('IdTelegram', None)
        ListaCorreos = request.json.get('ListaCorreos', None)

        # Actualizar en la base de datos
        mongo.db.datoscontacto.update_one(
            {'EmpleadoId': ObjectId(empleado_id)},
            {'$set': {
                'TelFijo': TelFijo,
                'TelCelular': TelCelular,
                'IdWhatsApp': IdWhatsApp,
                'IdTelegram': IdTelegram,
                'ListaCorreos': ListaCorreos
            }}
        )

        response = jsonify({'message': f'Datos de contacto para el empleado {empleado_id} actualizados exitosamente'})
        response.status_code = 200 # Establecer el código de estado HTTP 200 (OK)
        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500 # Manejar errores y devolver una respuesta JSON con estado 500 (Internal Server Error)
    
def guardar_coordenadas_en_db(mongo, latitude, longitude):
    try:
        # Insertar en la base de datos
        id = mongo.db.coordenadas.insert_one({
            'latitude': latitude,
            'longitude': longitude
        })

        response = {
            '_id': str(id),
            'latitude': latitude,
            'longitude': longitude
        }

        return response

    except Exception as e:
        raise Exception(f"Error al guardar las coordenadas en la base de datos: {str(e)}")

########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response