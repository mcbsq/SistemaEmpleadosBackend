from flask import request, jsonify
from flask_jwt_extended import get_jwt
from .logic import (
    create_or_update_expediente,
    get_expedienteclinicos_by_empleado,
    get_expedienteclinico,
    delete_expedienteclinico,
    update_expedienteclinico_empleado,
)
from api.auth_decorators import require_roles, require_self_or_roles

# Dato sensible (salud) — se trata con el criterio más estricto de todo el
# proyecto: EMPLOYEE solo puede tocar su propio expediente, nunca el de
# nadie más, y el borrado queda reservado a ADMIN/SUPER_ADMIN.


def setup_expedienteclinico_routes(app, mongo):

    @app.route('/expedienteclinico', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def create_expediente_route():
        data = request.get_json(silent=True) or {}
        empleado_id = data.get('empleado_id')
        if not empleado_id:
            return jsonify({'error': 'empleado_id es requerido'}), 400

        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        if role == 'EMPLOYEE' and str(identity.get('empleado_id')) != str(empleado_id):
            return jsonify({'error': 'Acceso no autorizado'}), 403

        return create_or_update_expediente(mongo, empleado_id, data)

    @app.route('/expedienteclinico/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def get_expediente_by_empleado_route(empleado_id):
        return get_expedienteclinicos_by_empleado(mongo, empleado_id)

    @app.route('/expedienteclinico/<id>', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_expediente_route(id):
        return get_expedienteclinico(mongo, id)

    @app.route('/expedienteclinico/empleado/<empleado_id>', methods=['PUT'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def update_expediente_route(empleado_id):
        data = request.get_json(silent=True) or {}
        return update_expedienteclinico_empleado(mongo, empleado_id, data)

    @app.route('/expedienteclinico/<empleado_id>', methods=['DELETE'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def delete_expediente_route(empleado_id):
        return delete_expedienteclinico(mongo, empleado_id)