from flask_jwt_extended import jwt_required, get_jwt

from .logic import (
    listar_notificaciones, contar_no_leidas, marcar_leida,
    marcar_todas_leidas, eliminar_notificacion,
)


def setup_notificaciones_routes(app, mongo):

    def _usuario_actual():
        identity = get_jwt()
        return identity.get('user') if isinstance(identity, dict) else None

    @app.route('/notificaciones', methods=['GET'])
    @jwt_required()
    def listar_notificaciones_route():
        return listar_notificaciones(mongo, _usuario_actual())

    @app.route('/notificaciones/no-leidas/count', methods=['GET'])
    @jwt_required()
    def contar_no_leidas_route():
        return contar_no_leidas(mongo, _usuario_actual())

    @app.route('/notificaciones/<notif_id>/leer', methods=['PATCH'])
    @jwt_required()
    def marcar_leida_route(notif_id):
        return marcar_leida(mongo, _usuario_actual(), notif_id)

    @app.route('/notificaciones/leer-todas', methods=['PATCH'])
    @jwt_required()
    def marcar_todas_leidas_route():
        return marcar_todas_leidas(mongo, _usuario_actual())

    @app.route('/notificaciones/<notif_id>', methods=['DELETE'])
    @jwt_required()
    def eliminar_notificacion_route(notif_id):
        return eliminar_notificacion(mongo, _usuario_actual(), notif_id)
