from flask import request
from .logic import get_config, update_config
from api.auth_decorators import require_roles


def setup_org_routes(app, mongo):

    # Lectura abierta a cualquier sesión válida — el frontend la usa para
    # aplicar branding/módulos antes de saber si el usuario es admin.
    @app.route('/org/<org_id>/config', methods=['GET'])
    def get_org_config_route(org_id):
        return get_config(mongo, org_id)

    # Solo SUPER_ADMIN decide cómo se ve y qué expone el sistema completo
    # (pensado para reventa: nada de esto debería requerir tocar código).
    @app.route('/org/<org_id>/config', methods=['PATCH'])
    @require_roles('SUPER_ADMIN')
    def update_org_config_route(org_id):
        data = request.get_json(silent=True) or {}
        return update_config(mongo, org_id, data)
