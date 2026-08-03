from flask import request, jsonify
from flask_jwt_extended import get_jwt, jwt_required

from api.auth_decorators import require_roles
from .logic import (
    listar_vacantes, crear_vacante, actualizar_vacante, eliminar_vacante,
    listar_candidatos, crear_candidato, actualizar_etapa_candidato, eliminar_candidato,
    evaluar_candidato, CRITERIOS_RECLUTAMIENTO,
)

ROLES_RECLUTAMIENTO = ("ADMIN", "SUPER_ADMIN")


def setup_reclutamiento_routes(app, mongo):

    @app.route('/reclutamiento/criterios', methods=['GET'])
    @jwt_required()
    def listar_criterios_reclutamiento_route():
        return jsonify(CRITERIOS_RECLUTAMIENTO), 200

    @app.route('/vacantes', methods=['GET'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def listar_vacantes_route():
        return listar_vacantes(mongo)

    @app.route('/vacantes', methods=['POST'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def crear_vacante_route():
        return crear_vacante(mongo, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/vacantes/<vacante_id>', methods=['PATCH'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def actualizar_vacante_route(vacante_id):
        return actualizar_vacante(mongo, vacante_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/vacantes/<vacante_id>', methods=['DELETE'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def eliminar_vacante_route(vacante_id):
        return eliminar_vacante(mongo, vacante_id, get_jwt())

    @app.route('/vacantes/<vacante_id>/candidatos', methods=['GET'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def listar_candidatos_route(vacante_id):
        return listar_candidatos(mongo, vacante_id)

    @app.route('/vacantes/<vacante_id>/candidatos', methods=['POST'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def crear_candidato_route(vacante_id):
        return crear_candidato(mongo, vacante_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/candidatos/<candidato_id>/etapa', methods=['PATCH'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def actualizar_etapa_route(candidato_id):
        data = request.get_json(silent=True) or {}
        return actualizar_etapa_candidato(mongo, candidato_id, data.get('etapa'), get_jwt())

    @app.route('/candidatos/<candidato_id>/evaluar', methods=['PUT'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def evaluar_candidato_route(candidato_id):
        return evaluar_candidato(mongo, candidato_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/candidatos/<candidato_id>', methods=['DELETE'])
    @require_roles(*ROLES_RECLUTAMIENTO)
    def eliminar_candidato_route(candidato_id):
        return eliminar_candidato(mongo, candidato_id, get_jwt())
