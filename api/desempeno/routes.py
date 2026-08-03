from flask import request, jsonify
from flask_jwt_extended import get_jwt, jwt_required

from api.auth_decorators import require_roles, require_self_or_roles
from .logic import (
    listar_ciclos, crear_ciclo, cerrar_ciclo, listar_evaluaciones_ciclo,
    get_evaluacion, get_evaluacion_activa_empleado, guardar_metas,
    guardar_autoevaluacion, guardar_evaluacion_jefe, CRITERIOS_DESEMPENO,
)

ROLES_GESTION = ("ADMIN", "SUPER_ADMIN")


def setup_desempeno_routes(app, mongo):

    @app.route('/desempeno/criterios', methods=['GET'])
    @jwt_required()
    def listar_criterios_desempeno_route():
        return jsonify(CRITERIOS_DESEMPENO), 200

    @app.route('/desempeno/ciclos', methods=['GET'])
    @require_roles(*ROLES_GESTION)
    def listar_ciclos_route():
        return listar_ciclos(mongo)

    @app.route('/desempeno/ciclos', methods=['POST'])
    @require_roles(*ROLES_GESTION)
    def crear_ciclo_route():
        return crear_ciclo(mongo, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/desempeno/ciclos/<ciclo_id>/cerrar', methods=['PATCH'])
    @require_roles(*ROLES_GESTION)
    def cerrar_ciclo_route(ciclo_id):
        return cerrar_ciclo(mongo, ciclo_id, get_jwt())

    @app.route('/desempeno/ciclos/<ciclo_id>/evaluaciones', methods=['GET'])
    @require_roles(*ROLES_GESTION)
    def listar_evaluaciones_route(ciclo_id):
        return listar_evaluaciones_ciclo(mongo, ciclo_id)

    @app.route('/desempeno/evaluaciones/<evaluacion_id>', methods=['GET'])
    @jwt_required()
    def get_evaluacion_route(evaluacion_id):
        return get_evaluacion(mongo, evaluacion_id)

    @app.route('/desempeno/empleado/<empleado_id>/activa', methods=['GET'])
    @require_self_or_roles('empleado_id', *ROLES_GESTION)
    def get_evaluacion_activa_route(empleado_id):
        return get_evaluacion_activa_empleado(mongo, empleado_id)

    @app.route('/desempeno/evaluaciones/<evaluacion_id>/metas', methods=['PUT'])
    @jwt_required()
    def guardar_metas_route(evaluacion_id):
        data = request.get_json(silent=True) or {}
        return guardar_metas(mongo, evaluacion_id, data.get('metas', []), get_jwt())

    @app.route('/desempeno/evaluaciones/<evaluacion_id>/autoevaluacion', methods=['PUT'])
    @jwt_required()
    def guardar_autoevaluacion_route(evaluacion_id):
        return guardar_autoevaluacion(mongo, evaluacion_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/desempeno/evaluaciones/<evaluacion_id>/jefe', methods=['PUT'])
    @require_roles(*ROLES_GESTION)
    def guardar_evaluacion_jefe_route(evaluacion_id):
        return guardar_evaluacion_jefe(mongo, evaluacion_id, request.get_json(silent=True) or {}, get_jwt())
