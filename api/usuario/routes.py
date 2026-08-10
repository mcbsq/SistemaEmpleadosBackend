from flask import request, jsonify
from flask_jwt_extended import get_jwt
from .logic import (create_usuario, get_usuarios, get_usuario,
                    delete_usuario, update_usuario, usuario_existente)
import logging
from api.auth_decorators import require_roles

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def setup_usuario_routes(app, mongo):

    @app.route('/usuario', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def get_usuario_list_route():
        return get_usuarios(mongo)

    # CRÍTICO — antes sin protección alguna: cualquiera podía crear una
    # cuenta con "role": "SUPER_ADMIN" sin token. Ahora SUPER_ADMIN
    # únicamente. Aquí también se asignan las áreas de un ADMIN.
    @app.route('/usuario', methods=['POST'])
    @require_roles('SUPER_ADMIN')
    def create_usuario_route():
        body                 = request.get_json() or {}
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
        return update_usuario(mongo, id, user, password, role,
                               areas_administradas=areas_administradas, identity=get_jwt())

    @app.route('/usuario/<id>', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def delete_usuario_route(id):
        return delete_usuario(mongo, id)