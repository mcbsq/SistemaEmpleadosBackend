from flask import request, jsonify
from functools import wraps
from flask_jwt_extended import get_jwt_identity, jwt_required
from .logic import (create_empleado, get_empleados, get_empleado, delete_empleado, update_empleado)
from .logic import aprobar_empleado


def require_admin(f):
    @wraps(f)
    @jwt_required()
    def decorated(*args, **kwargs):
        user = get_jwt_identity()
        role = user.get('role') if isinstance(user, dict) else None
        if role not in ('ADMIN', 'SUPER_ADMIN'):
            return jsonify({"error": "Acceso no autorizado"}), 403
        return f(*args, **kwargs)
    return decorated


def setup_empleados_routes(app, mongo):

    @app.route('/empleados', methods=['POST'])
    def create_empleado_route():
        return create_empleado(mongo)

    @app.route('/empleados', methods=['GET'])
    def get_empleados_route():
        return get_empleados(mongo)

    @app.route('/empleados/<id>', methods=['GET'])
    def get_empleado_route(id):
        return get_empleado(id, mongo)

    @app.route('/empleados/<id>', methods=['PUT'])
    def update_empleado_route(id):
        return update_empleado(id, mongo)

    @app.route('/empleados/<id>', methods=['DELETE'])
    def delete_empleado_route(id):
        return delete_empleado(id, mongo)

    @app.route('/empleados/<empleado_id>/aprobar', methods=['PATCH'])
    @require_admin
    def aprobar_empleado_route(empleado_id):
        return aprobar_empleado(mongo, empleado_id)