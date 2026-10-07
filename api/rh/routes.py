from flask import request, jsonify
from flask_jwt_extended import get_jwt, jwt_required
from .logic import (create_rh, get_rhs, get_rh_by_empleado_id, delete_rh_by_empleado_id, update_rh)
from api.auth_decorators import require_roles, require_self_or_roles
from core.permissions import require_roles_or_permission
from core.visibilidad_perfil import require_seccion


def setup_rh_routes(app, mongo):

    # Catálogo de bancos SPEI; con ?clabe= dice de qué banco es esa CLABE
    # y si es válida (para mostrarlo mientras se captura).
    @app.route('/bancos', methods=['GET'])
    @jwt_required()
    def bancos_route():
        from core.bancos_mx import catalogo, banco_de_clabe
        from core.validadores_mx import validar_clabe, normalizar
        clabe = normalizar(request.args.get('clabe', ''))
        if clabe:
            return jsonify({'clabe': clabe, 'banco': banco_de_clabe(clabe), 'error': validar_clabe(clabe)}), 200
        return jsonify(catalogo()), 200

    @app.route('/rh', methods=['POST'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def create_rh_route():
        data = request.get_json()
        empleado_id = data.get('empleado_id')
        return create_rh(mongo, empleado_id, data)

    # Solo lectura de la lista completa (sin crear/editar/borrar): CONTADOR
    # (permiso ver_rh) y PROJECT_MANAGER/JEFE_AREA, cuyos propios dashboards
    # ya llaman a esta ruta para mostrar puesto/departamento de su equipo.
    @app.route('/rh', methods=['GET'])
    @require_roles_or_permission(mongo, 'ver_rh', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR', 'PROJECT_MANAGER', 'JEFE_AREA')
    def get_rhs_route():
        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        return get_rhs(mongo, role=role)

    # Puesto, jefe y horario son datos administrados por RH, no autoeditables.
    # Los ven: el propio empleado, RH, su jefe directo y Contador; salarios y
    # bancarios se recortan/enmascaran según core/visibilidad_perfil.py.
    @app.route('/rh/<empleado_id>', methods=['GET'])
    @require_seccion(mongo, 'laboral')
    def get_rh_by_empleado_id_route(empleado_id):
        return get_rh_by_empleado_id(mongo, empleado_id, identity=get_jwt())

    @app.route('/rh/<empleado_id>', methods=['DELETE'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def delete_rh_by_empleado_id_route(empleado_id):
        return delete_rh_by_empleado_id(mongo, empleado_id)

    @app.route('/rh/<empleado_id>', methods=['PUT'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def update_rh_route(empleado_id):
        update_data = request.get_json()
        return update_rh(mongo, empleado_id, update_data, identity=get_jwt())