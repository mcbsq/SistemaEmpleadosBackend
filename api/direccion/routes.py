from flask import request
from .logic import (create_direccion, get_direccions, get_direccion, delete_direccion, update_direccion)

def setup_direccion_routes(app, mongo):
    
    @app.route('/direccion', methods=['POST'])
    def create_direccion_route():
        # Pasamos solo mongo, la lógica se encarga del resto
        return create_direccion(mongo)

    @app.route('/direccion', methods=['GET'])
    def get_direccions_route():
        return get_direccions(mongo)

    @app.route('/direccion/<id>', methods=['GET'])
    def get_direccion_route(id):
        return get_direccion(mongo, id)

    @app.route('/direccion/<id>', methods=['DELETE'])
    def delete_direccion_route(id):
        return delete_direccion(mongo, id)

    @app.route('/direccion/<id>', methods=['PUT'])
    def update_direccion_route(id):
        return update_direccion(mongo, id)