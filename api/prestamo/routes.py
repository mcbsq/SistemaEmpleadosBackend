from flask import request
from .logic import (create_prestamo, get_prestamos, get_prestamo, delete_prestamo,
                     update_prestamo, get_prestamos_by_empleado)
from api.auth_decorators import require_roles, require_self_or_roles
from api.validation_utils import require_fields

_CAMPOS_PRESTAMO = (
    'MontoPrestamo', 'TasaInteres', 'FecSolicitud', 'FecAprobacion',
    'FecVencimiento', 'PlazoMeses', 'MontoPendiente', 'PagosRealizados',
    'CuotaMensual', 'MetodoPago',
)


def setup_prestamo_routes(app, mongo):
    @app.route('/prestamo', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def create_prestamo_route():
        data = request.get_json(silent=True) or {}
        error = require_fields(data, *_CAMPOS_PRESTAMO)
        if error:
            return error
        return create_prestamo(
            mongo,
            data['MontoPrestamo'], data['TasaInteres'], data['FecSolicitud'],
            data['FecAprobacion'], data['FecVencimiento'], data['PlazoMeses'],
            data['MontoPendiente'], data['PagosRealizados'], data['CuotaMensual'],
            data['MetodoPago'], empleado_id=data.get('empleado_id'),
        )

    @app.route('/prestamo', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_prestamos_route():
        return get_prestamos(mongo)

    # Nuevo: el propio empleado puede consultar sus préstamos.
    @app.route('/prestamo/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def get_prestamos_by_empleado_route(empleado_id):
        return get_prestamos_by_empleado(mongo, empleado_id)

    @app.route('/prestamo/<id>', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_prestamo_route(id):
        return get_prestamo(mongo, id)

    @app.route('/prestamo/<id>', methods=['DELETE'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def delete_prestamo_route(id):
        return delete_prestamo(mongo, id)

    @app.route('/prestamo/<_id>', methods=['PUT'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def update_prestamo_route(_id):
        data = request.get_json(silent=True) or {}
        error = require_fields(data, *_CAMPOS_PRESTAMO)
        if error:
            return error
        return update_prestamo(
            mongo, _id,
            data['MontoPrestamo'], data['TasaInteres'], data['FecSolicitud'],
            data['FecAprobacion'], data['FecVencimiento'], data['PlazoMeses'],
            data['MontoPendiente'], data['PagosRealizados'], data['CuotaMensual'],
            data['MetodoPago'],
        )