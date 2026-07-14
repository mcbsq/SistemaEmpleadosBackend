from flask import request
from .logic import (create_educacion, get_educacion_by_empleado, delete_educacion, update_educacion, get_educacion)
from api.auth_decorators import require_roles, require_self_or_roles


def setup_educacion_routes(app, mongo):
    @app.route('/educacion', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def create_educacion_route():
        data = request.json
        empleado_id = data.get('empleado_id')
        return create_educacion(mongo, empleado_id, data)

    @app.route('/educacion/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def get_educacion_by_empleado_route(empleado_id):
        return get_educacion_by_empleado(mongo, empleado_id)

    @app.route('/educacion', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_educacion_route():
        return get_educacion(mongo)

    @app.route('/educacion/<empleado_id>', methods=['DELETE'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def delete_educacion_route(empleado_id):
        return delete_educacion(mongo, empleado_id)

    @app.route('/educacion/<empleado_id>', methods=['PUT'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def update_educacion_route(empleado_id):
        data = request.get_json()
        return update_educacion(mongo, empleado_id, data)