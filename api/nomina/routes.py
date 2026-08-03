from flask import request, jsonify
from flask_jwt_extended import get_jwt

from api.auth_decorators import require_roles, require_self_or_roles
from .logic import get_parametros_route, guardar_parametros, calcular_nomina

ROLES_NOMINA = ("ADMIN", "SUPER_ADMIN", "CONTADOR")


def setup_nomina_routes(app, mongo):

    @app.route('/nomina/parametros', methods=['GET'])
    @require_roles(*ROLES_NOMINA)
    def get_parametros_nomina_route():
        return get_parametros_route(mongo)

    @app.route('/nomina/parametros', methods=['PUT'])
    @require_roles(*ROLES_NOMINA)
    def put_parametros_nomina_route():
        data = request.get_json(silent=True) or {}
        return guardar_parametros(mongo, "default", data, get_jwt())

    @app.route('/nomina/calcular/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', *ROLES_NOMINA)
    def calcular_nomina_route(empleado_id):
        periodo = request.args.get('periodo', 'mensual')
        if periodo not in ('mensual', 'quincenal'):
            return jsonify({'error': 'periodo debe ser mensual o quincenal'}), 400
        return calcular_nomina(mongo, empleado_id, periodo)
