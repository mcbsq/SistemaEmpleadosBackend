from flask import request
from .logic import (create_catalogodepto, get_catalogodeptos, get_catalogodepto, delete_catalogodepto, update_catalogodepto)
from api.auth_decorators import require_roles
from api.validation_utils import require_fields


def setup_catalogodepto_routes(app, mongo):
    @app.route('/catalogodepto', methods=['POST'])
    @require_roles('SUPER_ADMIN')
    def create_catalogodepto_route():
        data = request.get_json(silent=True) or {}
        error = require_fields(data, 'NombreDepto', 'Descripcion', 'Poblacion')
        if error:
            return error
        return create_catalogodepto(mongo, data['NombreDepto'], data['Descripcion'], data['Poblacion'], data.get('DeptoPadre'))

    @app.route('/catalogodepto', methods=['GET'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def get_catalogodeptos_route():
        return get_catalogodeptos(mongo)

    @app.route('/catalogodepto/<id>', methods=['GET'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def get_catalogodepto_route(id):
        return get_catalogodepto(mongo, id)

    @app.route('/catalogodepto/<id>', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def delete_catalogodepto_route(id):
        return delete_catalogodepto(mongo, id)

    @app.route('/catalogodepto/<_id>', methods=['PUT'])
    @require_roles('SUPER_ADMIN')
    def update_catalogodepto_route(_id):
        data = request.get_json(silent=True) or {}
        error = require_fields(data, 'NombreDepto', 'Descripcion', 'Poblacion')
        if error:
            return error
        return update_catalogodepto(mongo, _id, data['NombreDepto'], data['Descripcion'], data['Poblacion'], data.get('DeptoPadre'))