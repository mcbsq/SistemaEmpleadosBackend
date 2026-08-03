from flask import request, jsonify
from .logic import guardar_jerarquia_logic, obtener_jerarquia_logic
from api.auth_decorators import require_roles
from core.permissions import require_roles_or_permission


def setup_jerarquia_routes(app, mongo):
    @app.route('/jerarquia', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def guardar_jerarquia_route():
        data = request.get_json()
        return guardar_jerarquia_logic(mongo, data)

    # Los 4 roles especiales tienen "ver_organigrama" en su PERMISOS_DEFAULT.
    @app.route('/jerarquia', methods=['GET'])
    @require_roles_or_permission(mongo, 'ver_organigrama', 'EMPLOYEE', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR', 'PROJECT_MANAGER', 'JEFE_AREA', 'MEDICO')
    def obtener_jerarquia_route():
        return obtener_jerarquia_logic(mongo)