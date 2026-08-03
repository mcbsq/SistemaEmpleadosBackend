from flask import request
from flask_jwt_extended import get_jwt, jwt_required

from api.auth_decorators import require_roles
from .logic import get_catalogo_route, get_permisos_route, guardar_permisos, exportar_reporte, resumen_sistema


def setup_analitica_routes(app, mongo):

    @app.route('/analitica/catalogo', methods=['GET'])
    @jwt_required()
    def get_catalogo_analitica_route():
        return get_catalogo_route(mongo, get_jwt())

    @app.route('/analitica/resumen', methods=['GET'])
    @jwt_required()
    def get_resumen_analitica_route():
        return resumen_sistema(mongo, get_jwt())

    @app.route('/analitica/permisos', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def get_permisos_analitica_route():
        return get_permisos_route(mongo)

    @app.route('/analitica/permisos', methods=['PUT'])
    @require_roles('SUPER_ADMIN')
    def put_permisos_analitica_route():
        return guardar_permisos(mongo, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/analitica/reportes/<reporte_id>/export', methods=['GET'])
    @jwt_required()
    def export_reporte_route(reporte_id):
        return exportar_reporte(mongo, reporte_id, get_jwt())
