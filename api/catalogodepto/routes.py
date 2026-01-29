from flask import request
from .logic import (create_catalogodepto, get_catalogodeptos, get_catalogodepto, delete_catalogodepto, update_catalogodepto)

def setup_catalogodepto_routes(app, mongo):
    @app.route('/catalogodepto', methods=['POST'])
    def create_catalogodepto_route():
        NombreDepto = request.json['NombreDepto']
        Descripcion = request.json['Descripcion']
        Poblacion = request.json['Poblacion']
        # Llama a la función create_catalogodepto para crear un departamento
        return create_catalogodepto(mongo, NombreDepto, Descripcion, Poblacion)

    @app.route('/catalogodepto', methods=['GET'])
    def get_catalogodeptos_route():
        # Llama a la función get_catalogodeptos para obtener todos los departamentos
        return get_catalogodeptos(mongo)

    @app.route('/catalogodepto/<id>', methods=['GET'])
    def get_catalogodepto_route(id):
        # Llamar a la función get_catalogodepto para obtener un departamento por su ID
        return get_catalogodepto(mongo, id)

    @app.route('/catalogodepto/<id>', methods=['DELETE'])
    def delete_catalogodepto_route(id):
        # Llamar a la función delete_catalogodepto para eliminar un departamento por su ID
        return delete_catalogodepto(mongo, id)

    @app.route('/catalogodepto/<_id>', methods=['PUT'])
    def update_catalogodepto_route(_id):
        NombreDepto = request.json['NombreDepto']
        Descripcion = request.json['Descripcion']
        Poblacion = request.json['Poblacion']
        # Llamar a la función update_catalogodepto para actualizar un departamento por su ID
        return update_catalogodepto(mongo, _id, NombreDepto, Descripcion, Poblacion)