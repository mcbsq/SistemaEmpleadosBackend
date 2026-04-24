from flask import request
from .logic import (
    create_direccion,
    get_direccions,
    get_direccion,
    get_direccion_by_empleado,
    update_direccion,
    update_direccion_by_empleado,
    delete_direccion,
)


def setup_direccion_routes(app, mongo):

    @app.route('/direccion', methods=['POST'])
    def create_direccion_route():
        return create_direccion(mongo)

    @app.route('/direccion', methods=['GET'])
    def get_direccions_route():
        return get_direccions(mongo)

    @app.route('/direccion/<id>', methods=['GET'])
    def get_direccion_route(id):
        return get_direccion(mongo, id)

    # ── Rutas por empleado_id ─────────────────────────────────────────────────
    # Usadas por Perfil.js: GET y PUT /direccion/empleado/<empleado_id>

    @app.route('/direccion/empleado/<empleado_id>', methods=['GET'])
    def get_direccion_by_empleado_route(empleado_id):
        return get_direccion_by_empleado(mongo, empleado_id)

    @app.route('/direccion/empleado/<empleado_id>', methods=['PUT'])
    def update_direccion_by_empleado_route(empleado_id):
        return update_direccion_by_empleado(mongo, empleado_id)

    # ── Ruta original por _id ─────────────────────────────────────────────────

    @app.route('/direccion/<id>', methods=['PUT'])
    def update_direccion_route(id):
        return update_direccion(mongo, id)

    @app.route('/direccion/<id>', methods=['DELETE'])
    def delete_direccion_route(id):
        return delete_direccion(mongo, id)