from flask import request
from .logic import (create_comportamientolaboral, get_comportamientolaboral, get_comportamientolaborals, delete_comportamientolaboral, update_comportamientolaboral)

#COMPORTAMIENTOLABORAL
def setup_comportamientolaboral_routes(app, mongo):
    # Ruta para crear un nuevo comportamiento laboral
    @app.route('/comportamientolaboral', methods=['POST'])
    def create_comportamientolaboral_route():
        # Obtener datos del cuerpo de la solicitud HTTP
        Fecha = request.json['Fecha']
        Descripcion = request.json['Descripcion']
        Calificacion = request.json['Calificacion']
        # Llamar a la función create_comportamientolaboral para crear un comportamiento laboral
        return create_comportamientolaboral(mongo, Fecha, Descripcion, Calificacion)

    # Ruta para obtener todos los comportamientos laborales
    @app.route('/comportamientolaboral', methods=['GET'])
    def get_comportamientolaborals_route():
        return get_comportamientolaborals(mongo)

    # Ruta para obtener un comportamiento laboral por su ID
    @app.route('/comportamientolaboral/<id>', methods=['GET'])
    def get_comportamientolaboral_route(id):
        return get_comportamientolaboral(mongo, id)

    # Ruta para eliminar un comportamiento laboral por su ID
    @app.route('/comportamientolaboral/<id>', methods=['DELETE'])
    def delete_comportamientolaboral_route(id):
        return delete_comportamientolaboral(mongo, id)

    # Ruta para actualizar un comportamiento laboral por su ID
    @app.route('/comportamientolaboral/<_id>', methods=['PUT'])
    def update_comportamientolaboral_route(_id):
        # Obtener nuevos datos del cuerpo de la solicitud HTTP
        Fecha = request.json['Fecha']
        Descripcion = request.json['Descripcion']
        Calificacion = request.json['Calificacion']
        # Llamar a la función update_comportamientolaboral para actualizar un comportamiento laboral por su ID
        return update_comportamientolaboral(mongo, _id, Fecha, Descripcion, Calificacion)