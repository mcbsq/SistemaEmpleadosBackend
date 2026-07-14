from flask import request
from .logic import create_datoscontacto, get_datoscontacto_by_empleado, get_datoscontactos, delete_datoscontacto, update_datoscontacto
from api.auth_decorators import require_roles, require_self_or_roles


def setup_datoscontacto_routes(app, mongo):
    @app.route('/datoscontacto', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def create_datoscontacto_route():
        TelFijo = request.json.get('TelFijo', '')
        TelCelular = request.json.get('TelCelular', '')
        IdWhatsApp = request.json.get('IdWhatsApp', '')
        IdTelegram = request.json.get('IdTelegram', '')
        ListaCorreos = request.json.get('ListaCorreos', '')
        EmpleadoId = request.json.get('empleado_id', '')
        return create_datoscontacto(mongo, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos, EmpleadoId)

    @app.route('/datoscontacto/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def get_datoscontacto_by_empleado_route(empleado_id):
        return get_datoscontacto_by_empleado(mongo, empleado_id)

    @app.route('/datoscontacto', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_datoscontactos_route():
        return get_datoscontactos(mongo)

    @app.route('/datoscontacto/<id>', methods=['DELETE'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def delete_datoscontacto_route(id):
        return delete_datoscontacto(mongo, id)

    @app.route('/datoscontacto/empleado/<empleado_id>', methods=['PUT'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def update_datoscontacto_route(empleado_id):
        TelFijo = request.json.get('TelFijo', '')
        TelCelular = request.json.get('TelCelular', '')
        IdWhatsApp = request.json.get('IdWhatsApp', '')
        IdTelegram = request.json.get('IdTelegram', '')
        ListaCorreos = request.json.get('ListaCorreos', '')
        return update_datoscontacto(mongo, empleado_id, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos)