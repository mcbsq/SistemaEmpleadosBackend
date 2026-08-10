from flask import request
from flask_jwt_extended import get_jwt

from api.auth_decorators import require_roles, require_self_or_roles
from .logic import (
    listar_conexiones, crear_conexion, actualizar_conexion, eliminar_conexion,
    obtener_nomina_externa,
)


def setup_conexiones_externas_routes(app, mongo):

    @app.route('/conexiones-externas', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def listar_conexiones_route():
        return listar_conexiones(mongo)

    @app.route('/conexiones-externas', methods=['POST'])
    @require_roles('SUPER_ADMIN')
    def crear_conexion_route():
        return crear_conexion(mongo, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/conexiones-externas/<conexion_id>', methods=['PATCH'])
    @require_roles('SUPER_ADMIN')
    def actualizar_conexion_route(conexion_id):
        return actualizar_conexion(mongo, conexion_id, request.get_json(silent=True) or {}, get_jwt())

    @app.route('/conexiones-externas/<conexion_id>', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def eliminar_conexion_route(conexion_id):
        return eliminar_conexion(mongo, conexion_id, get_jwt())

    # Mismo criterio de acceso que el resto del perfil: el propio empleado o
    # un ADMIN/SUPER_ADMIN pueden ver su nómina externa.
    @app.route('/empleados/<empleado_id>/nomina-externa', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN')
    def obtener_nomina_externa_route(empleado_id):
        return obtener_nomina_externa(mongo, empleado_id)
