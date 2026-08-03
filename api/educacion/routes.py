from flask import request
from .logic import (create_educacion, get_educacion_by_empleado, delete_educacion, update_educacion, get_educacion)
from api.auth_decorators import require_roles, require_self_or_roles
from core.permissions import require_roles_or_permission


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

    # PROJECT_MANAGER/JEFE_AREA tienen "ver_habilidades" y sus dashboards
    # agregan skills del equipo desde esta ruta (educación no expone datos
    # médicos/financieros, solo formación y habilidades).
    @app.route('/educacion', methods=['GET'])
    @require_roles_or_permission(mongo, 'ver_habilidades', 'ADMIN', 'SUPER_ADMIN', 'PROJECT_MANAGER', 'JEFE_AREA')
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