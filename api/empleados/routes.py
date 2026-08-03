from flask import request, jsonify
from flask_jwt_extended import get_jwt
from .logic import (create_empleado, get_empleados, get_empleado, delete_empleado, update_empleado)
from .logic import aprobar_empleado
from api.auth_decorators import require_roles, require_self_or_roles
from core.permissions import require_roles_or_permission


def setup_empleados_routes(app, mongo):

    @app.route('/empleados', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def create_empleado_route():
        return create_empleado(mongo, identity=get_jwt())

    # CONTADOR/PROJECT_MANAGER/JEFE_AREA/MEDICO ya tienen "ver_empleados" en su
    # PERMISOS_DEFAULT (ver api/login/logic.py) y sus dashboards llaman a esta
    # ruta — sin ellos aquí, el permiso existía solo en el frontend y el
    # dashboard de cada rol mostraba puros ceros.
    @app.route('/empleados', methods=['GET'])
    @require_roles_or_permission(mongo, 'ver_empleados', 'EMPLOYEE', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR', 'PROJECT_MANAGER', 'JEFE_AREA', 'MEDICO')
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
        return delete_empleado(id, mongo, identity=get_jwt())

    @app.route('/empleados/<empleado_id>/aprobar', methods=['PATCH'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def aprobar_empleado_route(empleado_id):
        return aprobar_empleado(mongo, empleado_id)

    # Cumpleaños y aniversario ya NO se exportan como .ics — se notifican
    # dentro del sistema (ver core/fechas_especiales.py). El .ics quedó
    # reservado exclusivamente para vacaciones aprobadas (api/vacaciones/routes.py).