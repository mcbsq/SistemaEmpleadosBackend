from flask import Flask, jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
import logging

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG)

######################################################

#EDUCACION

app.logger.setLevel(logging.DEBUG)

def create_educacion(mongo, empleado_id, data):
    # Obtener los datos del cuerpo de la solicitud HTTP
    data = request.json
    empleado_id = data.get('empleado_id')

    # Registrar los datos recibidos en los registros de la aplicación
    app.logger.debug(f'Datos recibidos en la API: {data}')

    if empleado_id:
        educacion = []
        experiencia = []

        # Extraer y formatear los datos de educación y experiencia
        for edu in data.get('Educacion', []):
            educacion_item = {
                'Fecha': edu.get('Fecha'),
                'Titulo': edu.get('Titulo'),
                'Descripcion': edu.get('Descripcion')
            }
            educacion.append(educacion_item)

        for exp in data.get('Experiencia', []):
            experiencia_item = {
                'Fecha': exp.get('Fecha'),
                'Titulo': exp.get('Titulo'),
                'Descripcion': exp.get('Descripcion')
            }
            experiencia.append(experiencia_item)

        # Resto del código para insertar en la base de datos
        result = mongo.db.educacion.insert_one({
            'empleado_id': ObjectId(empleado_id),
            'Descripcion': data.get('Descripcion'),
            'Educacion': educacion,
            'Experiencia': experiencia,
            'Habilidades': data.get('Habilidades', {})
        })

        # Registrar el resultado de la inserción en la base de datos
        app.logger.debug(f'Resultado de la inserción en la base de datos: {result.inserted_id}')

        response = jsonify({
            '_id': str(result.inserted_id),
            'message': 'Datos de educación creados exitosamente'
        })
        response.status_code = 201
        return response
    else:
        # Manejar el caso en que falta el ID del empleado
        app.logger.debug('Falta el ID del empleado')
        return jsonify({'message': 'Falta el ID del empleado'}), 400
    
def obtener_lista_de_empleados(mongo):
    empleados = mongo.db.empleados.find()
    empleados_list = list(empleados)  # Convertir el cursor a una lista de Python
    return empleados_list

# Función para obtener todos los datos de educación (GET)
def get_educacion(mongo):
    educacion = mongo.db.educacion.find()
    educacion_list = list(educacion)  # Convertir el cursor a una lista de Python
    
    empleados = obtener_lista_de_empleados(mongo)  # Obtener la lista de empleados
    
    for educacion in educacion_list:
        empleado_id = educacion.get("empleado_id")
        empleado_nombre = None
        for empleado in empleados:
            if str(empleado.get("_id")) == str(empleado_id):
                empleado_nombre = f"{empleado.get('Nombre')} {empleado.get('ApelPaterno')} {empleado.get('ApelMaterno')}"
                break
        
        if empleado_nombre:
            educacion["NombreCompleto"] = empleado_nombre  # Agregar el nombre completo a educacion
        else:
            educacion["NombreCompleto"] = ""  # Si no se encuentra el empleado, establecer el nombre completo como una cadena vacía
    
    response = json_util.dumps(educacion_list)
    return Response(response, mimetype="application/json")



def get_educacion_by_empleado(mongo, empleado_id):
    try:
        empleado_object_id = ObjectId(empleado_id)
        educacion = mongo.db.educacion.find_one({'empleado_id': empleado_object_id})
        
        if educacion:
            # Asegúrate de que la estructura de la educación sea como se espera
            educacion_formato = {
                "_id": str(educacion["_id"]),
                "empleado_id": str(educacion["empleado_id"]),
                "Descripcion": educacion["Descripcion"],
                "Educacion": educacion["Educacion"],
                "Experiencia": educacion["Experiencia"],
                "Habilidades": educacion["Habilidades"]
            }

            # Devuelve la educación formateada como JSON
            response = jsonify(educacion_formato)
            app.logger.info(f"Datos de educación para el empleado {empleado_id} recuperados correctamente.")
            return response
        else:
            # Si no se encontró educación, devolver una respuesta 404
            app.logger.warning(f"No se encontraron datos de educación para el empleado {empleado_id}.")
            return jsonify({"error": "No se encontraron datos de educación para el empleado"}), 404
            
    except Exception as e:
        app.logger.error(f"Error al recuperar datos de educación para el empleado {empleado_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

def delete_educacion(mongo, empleado_id):
    try:
        # Convierte el empleado_id a ObjectId
        object_id = ObjectId(empleado_id)
        # Realiza la eliminación en la colección educacion
        result = mongo.db.educacion.delete_many({'empleado_id': object_id})
        if result.deleted_count > 0:
            response = jsonify({'message': 'educacion for empleado ' + empleado_id + ' deleted successfully'})
            response.status_code = 200
        else:
            response = jsonify({'message': 'No educacion found for empleado ' + empleado_id})
            response.status_code = 404

    except Exception as e:
        # Manejar errores y registrarlos en los registros de la aplicación
        response = jsonify({'error': str(e)})
        response.status_code = 500

    return response

def update_educacion(mongo, empleado_id, data):
    data = request.get_json()
    if data:
        # Resto del código para procesar la actualización en la base de datos
        result = mongo.db.educacion.update_one(
            {'empleado_id': ObjectId(empleado_id['$oid']) if '$oid' in empleado_id else ObjectId(empleado_id)},
            {'$set': {
                'Descripcion': data.get('Descripcion'),
                'Educacion': data.get('Educacion'),
                'Experiencia': data.get('Experiencia'),
                'Habilidades': data.get('Habilidades')
            }}
        )

        if result.modified_count > 0:
            response = jsonify({'message': 'Educacion ' + empleado_id + ' updated successfully'})
            response.status_code = 200
            return response
        else:
            response = jsonify({'message': 'Educacion ' + empleado_id + ' not found'})
            response.status_code = 404
            return response
    else:
        return jsonify({'error': 'Invalid JSON data'}), 400
    
########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response