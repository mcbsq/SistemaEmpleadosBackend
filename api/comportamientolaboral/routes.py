from flask import request
from .logic import (create_comportamientolaboral, get_comportamientolaboral, get_comportamientolaborals,
                     delete_comportamientolaboral, update_comportamientolaboral,
                     get_comportamientolaborals_by_empleado)
from api.auth_decorators import require_roles, require_self_or_roles
from api.validation_utils import require_fields


def setup_comportamientolaboral_routes(app, mongo):
    @app.route('/comportamientolaboral', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def create_comportamientolaboral_route():
        data = request.get_json(silent=True) or {}
        error = require_fields(data, 'Fecha', 'Descripcion', 'Calificacion')
        if error:
            return error
        return create_comportamientolaboral(
            mongo, data['Fecha'], data['Descripcion'], data['Calificacion'],
            empleado_id=data.get('empleado_id'),
        )

    @app.route('/comportamientolaboral', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_comportamientolaborals_route():
        return get_comportamientolaborals(mongo)

    # Nuevo: el propio empleado puede ver su historial de comportamiento laboral.
    @app.route('/comportamientolaboral/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def get_comportamientolaborals_by_empleado_route(empleado_id):
        return get_comportamientolaborals_by_empleado(mongo, empleado_id)

    @app.route('/comportamientolaboral/<id>', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_comportamientolaboral_route(id):
        return get_comportamientolaboral(mongo, id)

    @app.route('/comportamientolaboral/<id>', methods=['DELETE'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def delete_comportamientolaboral_route(id):
        return delete_comportamientolaboral(mongo, id)

    @app.route('/comportamientolaboral/<_id>', methods=['PUT'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def update_comportamientolaboral_route(_id):
        data = request.get_json(silent=True) or {}
        error = require_fields(data, 'Fecha', 'Descripcion', 'Calificacion')
        if error:
            return error
        return update_comportamientolaboral(mongo, _id, data['Fecha'], data['Descripcion'], data['Calificacion'])