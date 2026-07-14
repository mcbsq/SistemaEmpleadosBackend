from flask import request, Response
from .logic import (create_or_update_redsocial, get_redessociales_empleado, delete_redsocial, update_redessociales_empleado, get_redsocial)
from api.auth_decorators import require_roles, require_self_or_roles


def setup_redsocial_routes(app, mongo):
    @app.route('/redsocial', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def create_or_update_redsocial_route():
        data = request.get_json()
        empleado_id = data.get('empleado_id')
        redes_sociales = data.get('RedesSociales', [])
        return create_or_update_redsocial(mongo, empleado_id, redes_sociales)

    @app.route('/redsocial', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_redsocial_route():
        return get_redsocial(mongo)

    @app.route('/redsocial/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def get_redessociales_empleado_route(empleado_id):
        return get_redessociales_empleado(mongo, empleado_id)

    @app.route('/redsocial/<empleado_id>', methods=['DELETE'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def delete_redsocial_route(empleado_id):
        return delete_redsocial(mongo, empleado_id)

    @app.route('/redsocial/empleado/<empleado_id>', methods=['PUT'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def update_redessociales_empleado_route(empleado_id):
        redes_sociales_nuevas = request.get_json().get('RedesSociales', [])
        return update_redessociales_empleado(mongo, empleado_id, redes_sociales_nuevas)