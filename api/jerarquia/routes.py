from flask import request, jsonify
from .logic import guardar_jerarquia_logic, obtener_jerarquia_logic
from api.auth_decorators import require_roles


def setup_jerarquia_routes(app, mongo):
    @app.route('/jerarquia', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def guardar_jerarquia_route():
        data = request.get_json()
        return guardar_jerarquia_logic(mongo, data)

    @app.route('/jerarquia', methods=['GET'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN')
    def obtener_jerarquia_route():
        return obtener_jerarquia_logic(mongo)