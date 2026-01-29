from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId


def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

######################################################

#PRESTAMO

# Función para crear un nuevo préstamo en la base de datos
def create_prestamo(mongo):
    # Obtiene los datos del préstamo desde el cuerpo de la solicitud JSON
    MontoPrestamo = request.json['MontoPrestamo']
    TasaInteres = request.json['TasaInteres']
    FecSolicitud = request.json['FecSolicitud']
    FecAprobacion = request.json['FecAprobacion']
    FecVencimiento = request.json['FecVencimiento']
    PlazoMeses = request.json['PlazoMeses']
    MontoPendiente = request.json['MontoPendiente']
    PagosRealizados = request.json['PagosRealizados']
    CuotaMensual = request.json['CuotaMensual']
    MetodoPago = request.json['MetodoPago']

    # Verifica que todos los campos necesarios estén presentes
    if MontoPrestamo and TasaInteres and FecSolicitud and FecAprobacion and FecVencimiento and PlazoMeses and MontoPendiente and PagosRealizados and CuotaMensual and MetodoPago:
        # Inserta los datos en la colección 'prestamo' de la base de datos
        id = mongo.db.prestamo.insert_one(
            {'MontoPrestamo': MontoPrestamo, 'TasaInteres': TasaInteres, 'FecSolicitud': FecSolicitud, 'FecAprobacion': FecAprobacion, 'FecVencimiento': FecVencimiento, 'PlazoMeses': PlazoMeses, 'MontoPendiente': MontoPendiente, 'PagosRealizados': PagosRealizados, 'CuotaMensual': CuotaMensual, 'MetodoPago': MetodoPago})
        # Crea una respuesta JSON con los detalles del préstamo insertado y devuelve un estado 201 (Creado)
        response = jsonify({
            '_id': str(id),
            'MontoPrestamo': MontoPrestamo,
            'TasaInteres': TasaInteres,
            'FecSolicitud': FecSolicitud,
            'FecAprobacion': FecAprobacion,
            'FecVencimiento': FecVencimiento,
            'PlazoMeses': PlazoMeses,
            'MontoPendiente': MontoPendiente,
            'PagosRealizados': PagosRealizados,
            'CuotaMensual': CuotaMensual,
            'MetodoPago': MetodoPago
        })
        response.status_code = 201
        return response
    else:
        # Si falta algún campo, llama a la función que devuelve un error 404
        return not_found()

# Función para obtener todos los préstamos de la base de datos
def get_prestamos(mongo):
    prestamos = mongo.db.prestamo.find()
    response = json_util.dumps(prestamos)
    return Response(response, mimetype="application/json")

# Función para obtener un préstamo específico por su ID de la base de datos
def get_prestamo(mongo,id):
    # Busca el préstamo por su ID en la base de datos
    print(id)
    prestamo = mongo.db.prestamo.find_one({'_id': ObjectId(id), })
    response = json_util.dumps(prestamo)
    return Response(response, mimetype="application/json")

# Función para eliminar un préstamo específico por su ID de la base de datos
def delete_prestamo(mongo,id):
    # Elimina el préstamo por su ID en la base de datos
    mongo.db.prestamo.delete_one({'_id': ObjectId(id)})
    response = jsonify({'message': 'Prestamo' + id + ' Deleted Successfully'})
    response.status_code = 200
    return response

# Función para actualizar un préstamo específico por su ID en la base de datos
def update_prestamo(mongo,_id):
    # Obtiene los datos actualizados del préstamo desde el cuerpo de la solicitud JSON
    MontoPrestamo = request.json['MontoPrestamo']
    TasaInteres = request.json['TasaInteres']
    FecSolicitud = request.json['FecSolicitud']
    FecAprobacion = request.json['FecAprobacion']
    FecVencimiento = request.json['FecVencimiento']
    PlazoMeses = request.json['PlazoMeses']
    MontoPendiente = request.json['MontoPendiente']
    PagosRealizados = request.json['PagosRealizados']
    CuotaMensual = request.json['CuotaMensual']
    MetodoPago = request.json['MetodoPago']

    # Verifica que todos los campos necesarios estén presentes
    if MontoPrestamo and TasaInteres and FecSolicitud and FecAprobacion and FecVencimiento and PlazoMeses and MontoPendiente and PagosRealizados and CuotaMensual and MetodoPago:
        # Actualiza el préstamo en la base de datos con los nuevos datos
        mongo.db.prestamo.update_one(
            {'_id': ObjectId(_id['$oid']) if '$oid' in _id else ObjectId(_id)}, {'$set': {'MontoPrestamo': MontoPrestamo, 'TasaInteres': TasaInteres, 'FecSolicitud': FecSolicitud, 'FecAprobacion': FecAprobacion, 'FecVencimiento': FecVencimiento, 'PlazoMeses': PlazoMeses, 'MontoPendiente': MontoPendiente, 'PagosRealizados': PagosRealizados, 'CuotaMensual': CuotaMensual, 'MetodoPago': MetodoPago}})
        response = jsonify({'message': 'Prestamo' + _id + 'Updated Successfuly'})
        response.status_code = 200
        return response
    else:
      return not_found()
    
########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response