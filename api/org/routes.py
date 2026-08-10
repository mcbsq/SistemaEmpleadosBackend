from flask import request, jsonify, g
from .logic import get_config, update_config
from api.auth_decorators import require_roles


def setup_org_routes(app, mongo):

    # Lectura abierta a cualquier sesión válida — el frontend la usa para
    # aplicar branding/módulos antes de saber si el usuario es admin. Solo
    # expone branding/módulos (nada sensible), así que leer la config de
    # otra empresa por URL no filtra datos de negocio — pero escribir sí
    # debe quedar atado a la empresa real del token (ver PATCH abajo).
    @app.route('/org/<org_id>/config', methods=['GET'])
    def get_org_config_route(org_id):
        return get_config(mongo, org_id)

    # Solo SUPER_ADMIN decide cómo se ve y qué expone el sistema completo
    # (pensado para reventa: nada de esto debería requerir tocar código).
    # Multi-tenencia: un SUPER_ADMIN solo puede editar la config de SU
    # PROPIA empresa — sin este chequeo, cambiar el org_id en la URL
    # permitiría pisar el branding de otra empresa.
    @app.route('/org/<org_id>/config', methods=['PATCH'])
    @require_roles('SUPER_ADMIN')
    def update_org_config_route(org_id):
        if org_id != g.get("org_id"):
            return jsonify({"error": "No puedes editar la configuración de otra empresa"}), 403
        data = request.get_json(silent=True) or {}
        return update_config(mongo, org_id, data)
