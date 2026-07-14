from flask import request
from .logic import (
    create_direccion,
    get_direccions,
    get_direccion,
    get_direccion_by_empleado,
    update_direccion,
    update_direccion_by_empleado,
    delete_direccion,
)
from api.auth_decorators import require_roles, require_self_or_roles


def setup_direccion_routes(app, mongo):

    @app.route('/direccion', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def create_direccion_route():
        return create_direccion(mongo)

    @app.route('/direccion', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_direccions_route():
        return get_direccions(mongo)

    @app.route('/direccion/<id>', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_direccion_route(id):
        return get_direccion(mongo, id)

    @app.route('/direccion/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def get_direccion_by_empleado_route(empleado_id):
        return get_direccion_by_empleado(mongo, empleado_id)

    @app.route('/direccion/empleado/<empleado_id>', methods=['PUT'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def update_direccion_by_empleado_route(empleado_id):
        return update_direccion_by_empleado(mongo, empleado_id)

    @app.route('/direccion/<id>', methods=['PUT'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def update_direccion_route(id):
        return update_direccion(mongo, id)

    @app.route('/direccion/<id>', methods=['DELETE'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def delete_direccion_route(id):
        return delete_direccion(mongo, id)