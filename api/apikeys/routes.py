from flask import request, jsonify
from flask_jwt_extended import get_jwt

from api.auth_decorators import require_roles
from .logic import (
    listar_api_keys, crear_api_key, revocar_api_key, eliminar_api_key,
    SCOPES_DISPONIBLES,
)


def setup_apikeys_routes(app, mongo):

    # Gestión de API keys: solo SUPER_ADMIN — una key concede acceso de
    # LECTURA a datos de toda la empresa sin pasar por el rol de nadie, así
    # que su alcance debe decidirlo quien administra el sistema completo.
    @app.route('/apikeys/scopes', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def get_scopes_route():
        return jsonify(SCOPES_DISPONIBLES), 200

    @app.route('/apikeys', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def listar_apikeys_route():
        return listar_api_keys(mongo)

    @app.route('/apikeys', methods=['POST'])
    @require_roles('SUPER_ADMIN')
    def crear_apikey_route():
        data = request.get_json(silent=True) or {}
        identity = get_jwt()
        creado_por = identity.get('user') if isinstance(identity, dict) else None
        return crear_api_key(mongo, data, creado_por)

    @app.route('/apikeys/<key_id>/revocar', methods=['PATCH'])
    @require_roles('SUPER_ADMIN')
    def revocar_apikey_route(key_id):
        return revocar_api_key(mongo, key_id)

    @app.route('/apikeys/<key_id>', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def eliminar_apikey_route(key_id):
        return eliminar_api_key(mongo, key_id)
