from flask import request
from .logic import (create_personascontacto, get_personascontactos, get_personascontacto_by_empleado, delete_personascontacto, update_personascontacto_by_empleado)
from api.auth_decorators import require_roles, require_self_or_roles


def setup_personascontacto_routes(app, mongo):
    @app.route('/personascontacto', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def create_personascontacto_route():
        personalcontacto = request.json.get('personalcontacto', {})
        return create_personascontacto(mongo, personalcontacto)

    @app.route('/personascontacto', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_personascontactos_route():
        return get_personascontactos(mongo)

    @app.route('/personascontacto/empleado/<empleadoid>', methods=['GET'])
    @require_self_or_roles('empleadoid', 'ADMIN', 'SUPER_ADMIN')
    def get_personascontacto_by_empleado_route(empleadoid):
        return get_personascontacto_by_empleado(mongo, empleadoid)

    @app.route('/personascontacto/<empleadoid>', methods=['DELETE'])
    @require_self_or_roles('empleadoid', 'ADMIN', 'SUPER_ADMIN')
    def delete_personascontacto_route(empleadoid):
        return delete_personascontacto(mongo, empleadoid)

    @app.route('/personascontacto/empleado/<empleadoid>', methods=['PUT'])
    @require_self_or_roles('empleadoid', 'ADMIN', 'SUPER_ADMIN')
    def update_personascontacto_by_empleado_route(empleadoid):
        personal_contacto = request.json.get('personalcontacto', {})
        return update_personascontacto_by_empleado(mongo, empleadoid, personal_contacto)