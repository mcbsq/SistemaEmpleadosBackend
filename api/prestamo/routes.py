from flask import request
from .logic import (create_prestamo, get_prestamos, get_prestamo, delete_prestamo, update_prestamo)

# Esta función establece las rutas para las operaciones CRUD de préstamos
def setup_prestamo_routes(app, mongo):
    # Ruta para crear un nuevo préstamo
    @app.route('/prestamo', methods=['POST'])
    def create_prestamo_route():
        # Extrae los detalles del préstamo del cuerpo de la solicitud JSON
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
        # Llama a la función lógica para crear un nuevo préstamo con los datos proporcionados
        return create_prestamo(mongo, MontoPrestamo,TasaInteres,FecSolicitud,FecAprobacion,FecVencimiento,PlazoMeses,MontoPendiente,PagosRealizados,CuotaMensual,MetodoPago)

    # Ruta para obtener todos los préstamos
    @app.route('/prestamo', methods=['GET'])
    def get_prestamos_route():
        # Llama a la función lógica para obtener todos los préstamos registrados
        return get_prestamos(mongo)

    # Ruta para obtener un préstamo específico por su ID
    @app.route('/prestamo/<id>', methods=['GET'])
    def get_prestamo_route(id):
        # Llama a la función lógica para obtener los detalles de un préstamo específico
        return get_prestamo(mongo, id)

    # Ruta para eliminar un préstamo específico por su ID
    @app.route('/prestamo/<id>', methods=['DELETE'])
    def delete_prestamo_route(id):
        # Llama a la función lógica para eliminar un préstamo específico
        return delete_prestamo(mongo, id)

    # Ruta para actualizar un préstamo específico por su ID
    @app.route('/prestamo/<_id>', methods=['PUT'])
    def update_prestamo_route(_id):
        # Extrae los detalles del préstamo del cuerpo de la solicitud JSON para actualizar
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
        # Llama a la función lógica para actualizar un préstamo con los datos proporcionados
        return update_prestamo(mongo, _id, MontoPrestamo,TasaInteres,FecSolicitud,FecAprobacion,FecVencimiento,PlazoMeses,MontoPendiente,PagosRealizados,CuotaMensual,MetodoPago)