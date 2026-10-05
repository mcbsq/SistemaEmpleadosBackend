# api/bajas/routes.py
from flask import request, jsonify
from flask_jwt_extended import get_jwt, jwt_required

from api.auth_decorators import require_roles, rol_permitido
from api.nomina import prestaciones as P
from .logic import TIPOS_BAJA, dar_baja, reingresar, listar_bajas, rotacion


def setup_bajas_routes(app, mongo):

    @app.route('/bajas/tipos', methods=['GET'])
    @jwt_required()
    def tipos_baja_route():
        return jsonify([{"id": k, "label": v} for k, v in TIPOS_BAJA.items()]), 200

    @app.route('/empleados/<empleado_id>/baja', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def dar_baja_route(empleado_id):
        return dar_baja(mongo, empleado_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/empleados/<empleado_id>/reingreso', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def reingreso_route(empleado_id):
        return reingresar(mongo, empleado_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/bajas', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def listar_bajas_route():
        return jsonify(listar_bajas(mongo, P.parse_fecha(request.args.get('desde')),
                                    P.parse_fecha(request.args.get('hasta')))), 200

    @app.route('/rotacion', methods=['GET'])
    @jwt_required()
    def rotacion_route():
        # Administración y RH siempre; otros roles (p. ej. el director) solo si
        # el SUPER_ADMIN les dio el reporte "rotacion" en Analítica.
        claims = get_jwt()
        role = claims.get("role")
        if not rol_permitido(role, ("ADMIN", "SUPER_ADMIN")):
            from api.analitica.logic import get_permisos
            if "rotacion" not in get_permisos(mongo).get(role, []):
                return jsonify({"error": "No tienes permiso para ver la rotación"}), 403
        datos = rotacion(mongo, request.args.get('desde'), request.args.get('hasta'))
        if datos is None:
            return jsonify({"error": "Periodo inválido: usa desde/hasta como AAAA-MM"}), 400
        return jsonify(datos), 200
