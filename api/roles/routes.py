from flask import request, jsonify
from flask_jwt_extended import get_jwt
import logging
from api.auth_decorators import require_roles
from core.audit import registrar_auditoria


def setup_roles_routes(app, mongo):

    @app.route('/roles/custom', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_roles_custom():
        try:
            doc = mongo.db.roles_custom.find_one({'tipo': 'custom'})
            if not doc:
                return jsonify([]), 200
            return jsonify(doc.get('roles', [])), 200
        except Exception as e:
            logging.error(f"Error obteniendo roles custom: {e}")
            return jsonify([]), 200

    # Define los permisos disponibles en TODO el sistema — dejarlo abierto
    # (como estaba) equivale a que cualquiera pueda otorgarse cualquier
    # permiso a sí mismo. SUPER_ADMIN únicamente.
    @app.route('/roles/custom', methods=['POST'])
    @require_roles('SUPER_ADMIN')
    def save_roles_custom():
        try:
            data = request.get_json(silent=True) or []
            doc_antes = mongo.db.roles_custom.find_one({'tipo': 'custom'}) or {}
            mongo.db.roles_custom.update_one(
                {'tipo': 'custom'},
                {'$set': {'tipo': 'custom', 'roles': data}},
                upsert=True,
            )

            identity = get_jwt()
            registrar_auditoria(
                mongo,
                identity.get('user') if isinstance(identity, dict) else None,
                identity.get('role') if isinstance(identity, dict) else None,
                'update', 'roles_custom', None,
                cambios={
                    "roles": {"antes": doc_antes.get('roles', []), "despues": data},
                },
            )

            return jsonify({'message': 'Roles guardados', 'count': len(data)}), 200
        except Exception as e:
            logging.error(f"Error guardando roles custom: {e}")
            return jsonify({'error': str(e)}), 500