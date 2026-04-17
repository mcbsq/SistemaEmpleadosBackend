# api/usuario/routes.py
# Fix: GET /usuario devolvía 405 porque no estaba registrado.
# Ahora se separa el endpoint para lista completa (GET /usuario → todos)
# y se mantiene compatibilidad con el frontend que llama GET /usuario.

from flask import request, jsonify
from .logic import (create_usuario, get_usuarios, get_usuario,
                    delete_usuario, update_usuario, usuario_existente)
import logging
from functools import wraps
from flask_jwt_extended import get_jwt_identity, jwt_required

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def require_super_admin(f):
    @wraps(f)
    @jwt_required()
    def decorated(*args, **kwargs):
        user = get_jwt_identity()
        if isinstance(user, dict) and user.get('role') == 'SUPER_ADMIN':
            return f(*args, **kwargs)
        return jsonify({"error": "Acceso no autorizado"}), 403
    return decorated


def setup_usuario_routes(app, mongo):

    # ── GET /usuario  → devuelve todos los usuarios ─────────────────────────
    # El frontend hace GET /usuario (sin ID) para el RoleManager.
    # La ruta /usuarios (con 's') sigue existiendo como alias protegido.
    @app.route('/usuario', methods=['GET'])
    def get_usuario_list_route():
        return get_usuarios(mongo)

    # ── POST /usuario  → crear usuario ──────────────────────────────────────
    @app.route('/usuario', methods=['POST'])
    def create_usuario_route():
        user        = request.json.get('user')
        password    = request.json.get('password')
        empleado_id = request.json.get('empleado_id')
        role        = request.json.get('role', 'EMPLOYEE')

        if usuario_existente(mongo, user):
            return jsonify({'error': 'El usuario ya existe.'}), 400

        return create_usuario(mongo, user, password, empleado_id, role)

    # ── GET /usuarios  → alias protegido (super admin) ──────────────────────
    @app.route('/usuarios', methods=['GET'])
    @require_super_admin
    def get_usuarios_route():
        return get_usuarios(mongo)

    # ── GET /usuario/<id> ────────────────────────────────────────────────────
    @app.route('/usuario/<id>', methods=['GET'])
    def get_usuario_route(id):
        return get_usuario(mongo, id)

    # ── PUT /usuario/<id> ────────────────────────────────────────────────────
    @app.route('/usuario/<id>', methods=['PUT'])
    def update_usuario_route(id):
        data = request.get_json() or {}
        user     = data.get('user')
        password = data.get('password')
        role     = data.get('role')
        return update_usuario(mongo, id, user, password, role)

    # ── DELETE /usuario/<id> ─────────────────────────────────────────────────
    @app.route('/usuario/<id>', methods=['DELETE'])
    def delete_usuario_route(id):
        return delete_usuario(mongo, id)