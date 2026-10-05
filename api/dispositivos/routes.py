# api/dispositivos/routes.py — dispositivos de confianza (ver logic.py).
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt

from api.auth_decorators import require_roles
from api.login.logic import _issue_token_response
from core.audit import registrar_auditoria
from .logic import registrar, entrar, listar, revocar_uno, revocar_de_usuario


def setup_dispositivos_routes(app, mongo):

    # Registrar este celular como dispositivo de confianza (tras un login normal).
    @app.route('/dispositivos', methods=['POST'])
    @jwt_required()
    def registrar_dispositivo_route():
        return registrar(mongo, get_jwt(), request.get_json(silent=True) or {})

    # Entrar con la llave del dispositivo (la app la libera con Face ID / huella).
    @app.route('/login/dispositivo', methods=['POST'])
    def entrar_dispositivo_route():
        return entrar(mongo, request.get_json(silent=True) or {}, _issue_token_response)

    # Mis celulares de confianza.
    @app.route('/dispositivos', methods=['GET'])
    @jwt_required()
    def mis_dispositivos_route():
        c = get_jwt()
        return jsonify(listar(mongo, c.get('user'), c.get('org_id'))), 200

    # Quitar uno de mis celulares (lo hace la app al cerrar sesión).
    @app.route('/dispositivos/<dispositivo_id>', methods=['DELETE'])
    @jwt_required()
    def revocar_mi_dispositivo_route(dispositivo_id):
        c = get_jwt()
        revocar_uno(mongo, dispositivo_id, c.get('user'), c.get('org_id'))
        return jsonify({'message': 'Dispositivo desvinculado'}), 200

    def _cuenta(usuario_id):
        try:
            return mongo.db.usuario.find_one({'_id': ObjectId(usuario_id)})
        except (InvalidId, TypeError):
            return None

    # Administración (Cuentas): ver y desvincular los celulares de una cuenta,
    # p. ej. si alguien pierde su teléfono.
    @app.route('/usuario/<usuario_id>/dispositivos', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def dispositivos_de_cuenta_route(usuario_id):
        u = _cuenta(usuario_id)
        if not u:
            return jsonify({'error': 'Cuenta no encontrada'}), 404
        return jsonify(listar(mongo, u.get('user'), g.org_id)), 200

    @app.route('/usuario/<usuario_id>/dispositivos', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def desvincular_cuenta_route(usuario_id):
        u = _cuenta(usuario_id)
        if not u:
            return jsonify({'error': 'Cuenta no encontrada'}), 404
        n = revocar_de_usuario(mongo, u.get('user'), g.org_id, 'desvinculado por administración')
        c = get_jwt()
        registrar_auditoria(mongo, c.get('user'), c.get('role'), 'update', 'dispositivos', str(u['_id']),
                            detalle=f'Desvinculó {n} celular(es) de {u.get("user")}')
        return jsonify({'message': 'Celulares desvinculados', 'desvinculados': n}), 200
