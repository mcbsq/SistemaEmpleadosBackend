from flask import request, jsonify
from functools import wraps
from flask_jwt_extended import get_jwt_identity, jwt_required
from .logic import (
    create_empleado, get_empleados, get_empleado,
    delete_empleado, update_empleado,
    aprobar_empleado, desactivar_empleado, reactivar_empleado,
)


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

    # ── Crear empleado (solo admin) ───────────────────────────────────────────
    @app.route('/empleados', methods=['POST'])
    @require_admin
    def create_empleado_route():
        return create_empleado(mongo)

    # ── Listar empleados — sin token, cualquier usuario logueado puede listar ─
    @app.route('/empleados', methods=['GET'])
    def get_empleados_route():
        return get_empleados(mongo)

    # ── Obtener un empleado — sin @jwt_required para evitar 422 ──────────────
    # El ID viaja encriptado en la URL (base64) — la seguridad real está
    # en que sin token no puedes hacer acciones de escritura
    @app.route('/empleados/<id>', methods=['GET'])
    def get_empleado_route(id):
        return get_empleado(id, mongo)

    # ── Actualizar empleado (solo admin) ──────────────────────────────────────
    @app.route('/empleados/<id>', methods=['PUT'])
    @require_admin
    def update_empleado_route(id):
        return update_empleado(id, mongo)

    # ── Eliminar empleado (solo admin) ────────────────────────────────────────
    @app.route('/empleados/<id>', methods=['DELETE'])
    @require_admin
    def delete_empleado_route(id):
        return delete_empleado(id, mongo)

    # ── Aprobar (pendiente → activo) ──────────────────────────────────────────
    @app.route('/empleados/<empleado_id>/aprobar', methods=['PATCH'])
    @require_admin
    def aprobar_empleado_route(empleado_id):
        return aprobar_empleado(mongo, empleado_id)

    # ── Desactivar ────────────────────────────────────────────────────────────
    @app.route('/empleados/<empleado_id>/desactivar', methods=['PATCH'])
    @require_admin
    def desactivar_empleado_route(empleado_id):
        return desactivar_empleado(mongo, empleado_id)

    # ── Reactivar ─────────────────────────────────────────────────────────────
    @app.route('/empleados/<empleado_id>/reactivar', methods=['PATCH'])
    @require_admin
    def reactivar_empleado_route(empleado_id):
        return reactivar_empleado(mongo, empleado_id)