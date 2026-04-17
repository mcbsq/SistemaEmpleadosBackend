# api/expedienteclinico/routes.py
# Fix crítico: había DOS funciones setup_expedienteclinico_routes —
# Python solo registra la segunda, así que /expedienteclinico POST desaparecía
# y el preflight CORS fallaba porque la ruta no existía.
#
# PDFs: se aceptan como base64 en JSON (campo PDFSegurodegastosmedicos)
# y se guardan directamente en MongoDB. No se usa el sistema de archivos local.

from flask import request, jsonify
from .logic import (
    create_or_update_expediente,
    get_expedienteclinicos_by_empleado,
    get_expedienteclinico,
    delete_expedienteclinico,
    update_expedienteclinico_empleado,
)


def setup_expedienteclinico_routes(app, mongo):

    # ── POST  → crear / upsert expediente ───────────────────────────────────
    @app.route('/expedienteclinico', methods=['POST'])
    def create_expediente_route():
        data = request.get_json(silent=True) or {}
        empleado_id = data.get('empleado_id')
        if not empleado_id:
            return jsonify({'error': 'empleado_id es requerido'}), 400
        return create_or_update_expediente(mongo, empleado_id, data)

    # ── GET  /expedienteclinico/empleado/<id> ────────────────────────────────
    @app.route('/expedienteclinico/empleado/<empleado_id>', methods=['GET'])
    def get_expediente_by_empleado_route(empleado_id):
        return get_expedienteclinicos_by_empleado(mongo, empleado_id)

    # ── GET  /expedienteclinico/<id> ─────────────────────────────────────────
    @app.route('/expedienteclinico/<id>', methods=['GET'])
    def get_expediente_route(id):
        return get_expedienteclinico(mongo, id)

    # ── PUT  /expedienteclinico/empleado/<id> ────────────────────────────────
    @app.route('/expedienteclinico/empleado/<empleado_id>', methods=['PUT'])
    def update_expediente_route(empleado_id):
        data = request.get_json(silent=True) or {}
        return update_expedienteclinico_empleado(mongo, empleado_id, data)

    # ── DELETE  /expedienteclinico/<empleado_id> ─────────────────────────────
    @app.route('/expedienteclinico/<empleado_id>', methods=['DELETE'])
    def delete_expediente_route(empleado_id):
        return delete_expedienteclinico(mongo, empleado_id)