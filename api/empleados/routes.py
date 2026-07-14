from flask import request, jsonify
from flask_jwt_extended import get_jwt
from .logic import (create_empleado, get_empleados, get_empleado, delete_empleado, update_empleado)
from .logic import aprobar_empleado
from api.auth_decorators import require_roles, require_self_or_roles


def setup_empleados_routes(app, mongo):

    @app.route('/empleados', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def create_empleado_route():
        return create_empleado(mongo, identity=get_jwt())

    @app.route('/empleados', methods=['GET'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def get_empleados_route():
        return get_empleados(mongo, identity=get_jwt())

    @app.route('/empleados/<id>', methods=['GET'])
    @require_self_or_roles('id', 'ADMIN', 'SUPER_ADMIN')
    def get_empleado_route(id):
        return get_empleado(id, mongo, identity=get_jwt())

    @app.route('/empleados/<id>', methods=['PUT'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def update_empleado_route(id):
        return update_empleado(id, mongo, identity=get_jwt())

    @app.route('/empleados/<id>', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def delete_empleado_route(id):
        return delete_empleado(id, mongo)

    @app.route('/empleados/<empleado_id>/aprobar', methods=['PATCH'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def aprobar_empleado_route(empleado_id):
        return aprobar_empleado(mongo, empleado_id)