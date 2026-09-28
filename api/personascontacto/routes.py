from flask import request
from .logic import (get_personascontactos, get_personascontacto_by_empleado, delete_personascontacto, update_personascontacto_by_empleado)
from api.auth_decorators import require_roles, require_self_or_roles


def setup_personascontacto_routes(app, mongo):
    # POST /personascontacto (crear un solo contacto) se retiró — el PUT de
    # abajo hace upsert de la lista completa, así que crear el primer
    # contacto de emergencia de un empleado es solo mandar un arreglo de 1
    # elemento a ese mismo endpoint (ver contactoService.updatePersona).

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
        contactos = request.json.get('personalcontacto', [])
        return update_personascontacto_by_empleado(mongo, empleadoid, contactos)