from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId


def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

######################################################

#RECURSOS HUMANOS

# Función para crear o actualizar información de RH para un empleado específico
def create_rh(mongo, empleado_id, rh_data): 
    if request.is_json: 
        data = request.get_json() 
        # Extrae los datos de RH del cuerpo de la solicitud
        Puesto = data.get('Puesto', '') 
        JefeInmediato = data.get('JefeInmediato', '') 
        HorarioLaboral = data.get('HorarioLaboral', '') 
        ExpedienteDigitalPDF = data.get('ExpedienteDigitalPDF', '') 
 
        # Convierte el ID del empleado a ObjectId para MongoDB
        empleado_id = ObjectId(data.get('empleado_id', '')) 
         
        # Prepara el documento con los datos de RH 
        rh_data = { 
            'empleado_id': empleado_id, 
            'Puesto': Puesto, 
            'JefeInmediato': JefeInmediato, 
            'HorarioLaboral': HorarioLaboral, 
            'ExpedienteDigitalPDF': ExpedienteDigitalPDF 
        } 
 
        # Inserta o actualiza el documento en la base de datos
        id = mongo.db.rh.insert_one(rh_data) 
 
        # Devuelve una respuesta con los datos insertados/actualizados
        response = jsonify({ 
            '_id': str(id.inserted_id), 
            'empleado_id': str(empleado_id), 
            'Puesto': Puesto, 
            'JefeInmediato': JefeInmediato, 
            'HorarioLaboral': HorarioLaboral, 
            'ExpedienteDigitalPDF': ExpedienteDigitalPDF 
        }) 
 
        response.status_code = 201 
        return response 
    # Devuelve un error si la solicitud no es JSON o falta información
    return jsonify({'error': 'No data provided'}), 400 

def obtener_lista_de_empleados(mongo):
    empleados = mongo.db.empleados.find()
    empleados_list = list(empleados)  # Convertir el cursor a una lista de Python
    return empleados_list

# Función para obtener todos los registros de RH
def get_rhs(mongo):
    rhs = mongo.db.rh.find()
    rh_list = list(rhs)  # Convertir el cursor a una lista de Python
    
    empleados = obtener_lista_de_empleados(mongo)  # Obtener la lista de empleados
    
    for rhs in rh_list:
        empleado_id = rhs.get("empleado_id")
        empleado_nombre = None
        for empleado in empleados:
            if str(empleado.get("_id")) == str(empleado_id):
                empleado_nombre = f"{empleado.get('Nombre')} {empleado.get('ApelPaterno')} {empleado.get('ApelMaterno')}"
                break
        
        if empleado_nombre:
            rhs["NombreCompleto"] = empleado_nombre  # Agregar el nombre completo al dato de contacto
        else:
            rhs["NombreCompleto"] = ""  # Si no se encuentra el empleado, establecer el nombre completo como una cadena vacía
    
    response = json_util.dumps(rh_list)
    return Response(response, mimetype="application/json")

# Función para obtener información de RH de un empleado específico por ID
def get_rh_by_empleado_id(mongo,empleado_id):
    rh_data = mongo.db.rh.find_one({'empleado_id': ObjectId(empleado_id)}) 
     
    if rh_data: 
        # Convierte ObjectId a str para JSON serialization 
        rh_data['_id'] = str(rh_data['_id']) 
        rh_data['empleado_id'] = str(rh_data['empleado_id']) 
         
        return jsonify(rh_data) 
     
    return jsonify({'error': 'Rh data not found for empleado_id {}'.format(empleado_id)}), 404

# Función para eliminar información de RH de un empleado específico por ID
def delete_rh_by_empleado_id(mongo,empleado_id):
    result = mongo.db.rh.delete_one({'empleado_id': ObjectId(empleado_id)}) 
     
    if result.deleted_count > 0: 
        response = jsonify({'message': f'Recurso Humano for empleado_id {empleado_id} Deleted Successfully'}) 
        response.status_code = 200 
        return response 
    else: 
        return jsonify({'error': f'Rh data not found for empleado_id {empleado_id}'}), 404

# Función para actualizar información de RH de un empleado específico
def update_rh(mongo, empleado_id, rh_data):
    # Obtener el documento RH actual 
    rh_data = mongo.db.rh.find_one({'empleado_id': ObjectId(empleado_id)}) 
 
    if rh_data: 
        # Campos del documento actual 
        current_puesto = rh_data.get('Puesto', '') 
        current_jefe_inmediato = rh_data.get('JefeInmediato', '') 
        current_horario_laboral = rh_data.get('HorarioLaboral', {}) 
        current_expediente_digital_pdf = rh_data.get('ExpedienteDigitalPDF', '') 
 
        # Campos a actualizar 
        Puesto = request.json.get('Puesto', current_puesto) 
        JefeInmediato = request.json.get('JefeInmediato', current_jefe_inmediato) 
        HorarioLaboral = request.json.get('HorarioLaboral', current_horario_laboral) 
        ExpedienteDigitalPDF = request.json.get('ExpedienteDigitalPDF', current_expediente_digital_pdf) 
 
        # Actualizar el documento RH con los campos proporcionados 
        result = mongo.db.rh.update_one( 
            {'empleado_id': ObjectId(empleado_id)}, 
            {'$set': { 
                'Puesto': Puesto, 
                'JefeInmediato': JefeInmediato, 
                'HorarioLaboral': HorarioLaboral, 
                'ExpedienteDigitalPDF': ExpedienteDigitalPDF 
            }} 
        )

        if result.modified_count > 0: 
            response = jsonify({'message': f'Recurso Humano with empleado_id {empleado_id} updated successfully'}) 
            response.status_code = 200 
        else: 
            response = jsonify({'error': 'No matching Recurso Humano found'}) 
            response.status_code = 404 
 
        return response 
    else: 
        return jsonify({'error': 'Recurso Humano not found'}), 404
    
########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response