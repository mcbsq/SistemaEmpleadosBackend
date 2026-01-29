from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId

######################################################

#PERSONAS CONTACTO

# Función para crear un nuevo contacto de una persona en la base de datos.
def create_personascontacto(mongo, personalcontacto):
    # Recibe los datos del contacto de una persona y los inserta en la base de datos
    personalcontacto = request.json.get('personalcontacto', {})

    # Valida si se han proporcionado datos de contacto
    if not personalcontacto:
        return jsonify({'error': 'No data provided for personalcontacto'}), 400

    # Extrae los campos individuales del diccionario personalcontacto.
    # Si alguno de los campos no existe, se utiliza un valor vacío por defecto
    parenstesco = personalcontacto.get('parenstesco', '')
    nombreContacto = personalcontacto.get('nombreContacto', '')
    telefonoContacto = personalcontacto.get('telefonoContacto', '')
    correoContacto = personalcontacto.get('correoContacto', '')
    direccionContacto = personalcontacto.get('direccionContacto', '')
    empleadoid_str = personalcontacto.get('empleadoid', '')

    # Valida si los campos obligatorios 'parenstesco' y 'nombreContacto' están presentes
    if not parenstesco or not nombreContacto:
        return jsonify({'error': 'parenstesco and nombreContacto are required fields'}), 400

    try:
        # Intenta convertir el string empleadoid_str a un ObjectId de MongoDB
        empleadoid = ObjectId(empleadoid_str)
    except:
        return jsonify({'error': 'Invalid ObjectId for empleadoid'}), 400

    # Inserta los datos del nuevo contacto en la base de datos y obtiene el ID de inserción
    id = mongo.db.personascontacto.insert_one({
        'empleadoid': empleadoid,
        'parenstesco': parenstesco,
        'nombreContacto': nombreContacto,
        'telefonoContacto': telefonoContacto,
        'correoContacto': correoContacto,
        'direccionContacto': direccionContacto,
        
    })

    response = jsonify({
        '_id': str(id),
        'empleadoid': str(empleadoid),
        'parenstesco': parenstesco,
        'nombreContacto': nombreContacto,
        'telefonoContacto': telefonoContacto,
        'correoContacto': correoContacto,
        'direccionContacto': direccionContacto
        
    })
    response.status_code = 201
    return response

def obtener_lista_de_empleados(mongo):
    empleados = mongo.db.empleados.find()
    empleados_list = list(empleados)  # Convertir el cursor a una lista de Python
    return empleados_list

def get_personascontactos(mongo):
    personascontactos = mongo.db.personascontacto.find()
    personascontactos_list = list(personascontactos)

    empleados = obtener_lista_de_empleados(mongo)

    for personascontacto in personascontactos_list:
        empleado_id = personascontacto.get("empleadoid")
        empleado_nombre = None
        for empleado in empleados:
            if str(empleado.get("_id")) == str(empleado_id):
                empleado_nombre = f"{empleado.get('Nombre')} {empleado.get('ApelPaterno')} {empleado.get('ApelMaterno')}"
                break        
        if empleado_nombre:
            personascontacto["NombreCompleto"] = empleado_nombre  # Agregar el nombre completo al dato de contacto
        else:
            personascontacto["NombreCompleto"] = ""  # Si no se encuentra el empleado, establecer el nombre completo como una cadena vacía
    
    response = json_util.dumps(personascontactos_list)
    return Response(response, mimetype="application/json")


def get_personascontacto_by_empleado(mongo,empleadoid):
    try:
        empleadoid_obj = ObjectId(empleadoid)
        personas_contacto = mongo.db.personascontacto.find({'empleadoid': empleadoid_obj})

        # Convertir ObjectId a cadena antes de serializar
        personas_contacto_list = [{'_id': str(item['_id']), 'empleadoid': str(item['empleadoid']), 'parenstesco': item['parenstesco'], 'nombreContacto': item['nombreContacto'], 'telefonoContacto': item['telefonoContacto'], 'correoContacto': item['correoContacto'], 'direccionContacto': item['direccionContacto']} for item in personas_contacto]
        
        if not personas_contacto_list:
            return jsonify({"error": "Datos de contacto no encontrados"}), 404

        return jsonify(personas_contacto_list)
    
    except Exception as e:
        print("Error:", e)
        return jsonify({'message': f'Error al obtener personas de contacto por empleadoid: {str(e)}'}), 500


def delete_personascontacto(mongo,empleadoid):
    try:
        # Convierte el empleado_id a ObjectId
        object_id = ObjectId(empleadoid)
        
        # Realiza la eliminación en la colección personascontacto
        result = mongo.db.personascontacto.delete_one({'empleadoid': object_id})
        
        if result.deleted_count > 0:
            response = jsonify({'message': 'Persona Contacto ' + empleadoid + ' Deleted Successfully'})
            response.status_code = 200
        else:
            response = jsonify({'message': 'No Persona Contacto found for id ' + empleadoid})
            response.status_code = 404

    except Exception as e:
        response = jsonify({'error': str(e)})
        response.status_code = 500
    
    return response  

def update_personascontacto_by_empleado(mongo, empleadoid, personal_contacto):
    # Obtener los datos del JSON enviado en la solicitud
    personal_contacto = request.json.get('personalcontacto', {})

    # Validar si 'personalcontacto' está presente en los datos JSON
    if not personal_contacto:
        return jsonify({'error': 'No data provided for personalcontacto'}), 400

    # Extraer campos individuales de personal_contacto
    parenstesco = personal_contacto.get('parenstesco', '')
    nombre_contacto = personal_contacto.get('nombreContacto', '')
    telefono_contacto = personal_contacto.get('telefonoContacto', '')
    correo_contacto = personal_contacto.get('correoContacto', '')
    direccion_contacto = personal_contacto.get('direccionContacto', '')
    empleadoid_str = personal_contacto.get('empleadoid', '')

    # Validar si alguno de los campos requeridos está vacío
    if not parenstesco or not nombre_contacto:
        return jsonify({'error': 'parenstesco and nombreContacto are required fields'}), 400

    try:
        # Convertir empleadoid_str a ObjectId
        empleadoid = ObjectId(empleadoid_str)
    except:
        return jsonify({'error': 'Invalid ObjectId for empleadoid'}), 400

    # Actualizar el documento en la base de datos
    mongo.db.personascontacto.update_one(
        {'empleadoid': empleadoid},
        {'$set': {
            'parenstesco': parenstesco,
            'nombreContacto': nombre_contacto,
            'telefonoContacto': telefono_contacto,
            'correoContacto': correo_contacto,
            'direccionContacto': direccion_contacto
        }}
    )

    response = jsonify({
        'message': f'Persona Contacto Updated Successfully for empleado {empleadoid}'
    })
    response.status_code = 200
    return response

########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response