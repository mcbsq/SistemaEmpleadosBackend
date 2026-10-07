from flask import request, jsonify, g
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask_jwt_extended import get_jwt
from .logic import (create_usuario, get_usuarios, get_usuario,
                    delete_usuario, update_usuario, usuario_existente)
import logging
from api.auth_decorators import require_roles

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')


ROLES_QUE_RH_NO_PUEDE_CREAR = {'SUPER_ADMIN', 'ADMIN', 'RH'}


def setup_usuario_routes(app, mongo):

    def _cuenta_por_id(id):
        try:
            return mongo.db.usuario.find_one({'_id': ObjectId(id)})
        except (InvalidId, TypeError):
            return None

    @app.route('/usuario', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def get_usuario_list_route():
        return get_usuarios(mongo)

    # CRÍTICO — antes sin protección alguna: cualquiera podía crear una
    # cuenta con "role": "SUPER_ADMIN" sin token. Hoy: SUPER_ADMIN, y RH
    # (oct 2026) para dar acceso a las personas que contrata — pero RH NUNCA
    # puede crear cuentas con un rol igual o superior al suyo (ADMIN, RH,
    # SUPER_ADMIN) ni asignar áreas: eso sería auto-ascenderse.
    @app.route('/usuario', methods=['POST'])
    @require_roles('SUPER_ADMIN', 'RH')
    def create_usuario_route():
        body                 = request.get_json() or {}
        if get_jwt().get('role') == 'RH':
            if str(body.get('role') or 'EMPLOYEE').upper() in ROLES_QUE_RH_NO_PUEDE_CREAR:
                return jsonify({'error': 'Recursos Humanos no puede crear cuentas de administrador. Pídeselo al superadministrador.'}), 403
            body.pop('areas_administradas', None)
        user                 = body.get('user')
        password             = body.get('password')
        empleado_id          = body.get('empleado_id')
        role                 = body.get('role', 'EMPLOYEE')
        email                = body.get('email')
        areas_administradas  = body.get('areas_administradas')  # lista de depto_id, solo aplica si role == 'ADMIN'

        if usuario_existente(mongo, user, email):
            return jsonify({'error': 'El usuario ya existe.'}), 400

        return create_usuario(mongo, user, password, empleado_id, role,
                               email=email, areas_administradas=areas_administradas)

    @app.route('/usuarios', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def get_usuarios_route():
        return get_usuarios(mongo)

    @app.route('/usuario/<id>', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_usuario_route(id):
        return get_usuario(mongo, id)

    # SUPER_ADMIN únicamente: puede cambiar "role" y "areas_administradas"
    # de cualquier usuario. Abrir esto a ADMIN permitiría auto-ascenderse a
    # SUPER_ADMIN o auto-asignarse áreas que no le corresponden.
    @app.route('/usuario/<id>', methods=['PUT'])
    @require_roles('SUPER_ADMIN')
    def update_usuario_route(id):
        data                 = request.get_json() or {}
        user                 = data.get('user')
        password             = data.get('password')
        role                 = data.get('role')
        areas_administradas  = data.get('areas_administradas')
        antes = _cuenta_por_id(id)
        resp = update_usuario(mongo, id, user, password, role,
                               areas_administradas=areas_administradas, identity=get_jwt())
        status = resp[1] if isinstance(resp, tuple) else getattr(resp, 'status_code', 200)
        if antes and status == 200 and (password or (role and role != antes.get('role'))):
            # Contraseña restablecida o rol distinto: sus celulares de
            # confianza vuelven a pedir login (la sesión llevaba el rol viejo).
            from api.dispositivos.logic import revocar_de_usuario
            revocar_de_usuario(mongo, antes.get('user'), g.org_id, 'restablecimiento o cambio de rol')
        if antes and status == 200 and password:
            from api.login.sesion import marcar_atendida
            marcar_atendida(mongo, antes.get('user'), g.org_id)
        return resp

    @app.route('/usuario/<id>', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def delete_usuario_route(id):
        antes = _cuenta_por_id(id)
        resp = delete_usuario(mongo, id)
        if antes:
            from api.dispositivos.logic import revocar_de_usuario
            revocar_de_usuario(mongo, antes.get('user'), g.org_id, 'cuenta eliminada')
        return resp