from datetime import datetime, timezone

from flask import request, jsonify
from flask_jwt_extended import get_jwt

from api.auth_decorators import require_roles, require_self_or_roles
from .logic import (
    get_parametros_route, guardar_parametros, calcular_nomina,
    calcular_aguinaldo, reporte_aguinaldos,
    listar_horas_extra, registrar_horas_extra, resolver_horas_extra, eliminar_horas_extra,
    calcular_horas_extra_empleado,
)

ROLES_NOMINA = ("ADMIN", "SUPER_ADMIN", "CONTADOR")


def _anio():
    try:
        anio = int(request.args.get("anio") or datetime.now(timezone.utc).year)
    except ValueError:
        return None
    return anio if 2000 <= anio <= 2100 else None


def setup_nomina_routes(app, mongo):

    def _equipo(claims):
        """None = sin restricción; un JEFE_AREA solo ve/registra a su equipo directo."""
        if claims.get("role") != "JEFE_AREA":
            return None
        from api.empleados.logic import _equipo_directo_ids
        return {str(i) for i in _equipo_directo_ids(mongo, claims)}

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
        return calcular_nomina(mongo, empleado_id, periodo, mes=request.args.get('mes'))

    # ── Aguinaldo ────────────────────────────────────────────────────────
    @app.route('/nomina/aguinaldo', methods=['GET'])
    @require_roles(*ROLES_NOMINA)
    def reporte_aguinaldo_route():
        anio = _anio()
        if anio is None:
            return jsonify({'error': 'anio inválido'}), 400
        return reporte_aguinaldos(mongo, anio)

    @app.route('/nomina/aguinaldo/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', *ROLES_NOMINA)
    def aguinaldo_empleado_route(empleado_id):
        anio = _anio()
        if anio is None:
            return jsonify({'error': 'anio inválido'}), 400
        return calcular_aguinaldo(mongo, empleado_id, anio)

    # ── Horas extra ──────────────────────────────────────────────────────
    @app.route('/horas-extra', methods=['GET'])
    @require_roles(*ROLES_NOMINA, 'JEFE_AREA')
    def listar_horas_extra_route():
        return jsonify(listar_horas_extra(mongo, request.args, _equipo(get_jwt()))), 200

    @app.route('/horas-extra', methods=['POST'])
    @require_roles(*ROLES_NOMINA, 'JEFE_AREA')
    def registrar_horas_extra_route():
        claims = get_jwt()
        return registrar_horas_extra(mongo, request.get_json(silent=True) or {}, claims, _equipo(claims))

    @app.route('/horas-extra/<registro_id>', methods=['PATCH'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def resolver_horas_extra_route(registro_id):
        return resolver_horas_extra(mongo, registro_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/horas-extra/<registro_id>', methods=['DELETE'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def eliminar_horas_extra_route(registro_id):
        return eliminar_horas_extra(mongo, registro_id, get_jwt())

    @app.route('/nomina/horas-extra/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', *ROLES_NOMINA)
    def calcular_horas_extra_route(empleado_id):
        return calcular_horas_extra_empleado(mongo, empleado_id, request.args.get('mes'))
