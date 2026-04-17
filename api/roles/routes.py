from flask import request, jsonify
import logging

def setup_roles_routes(app, mongo):

    @app.route('/roles/custom', methods=['GET'])
    def get_roles_custom():
        try:
            doc = mongo.db.roles_custom.find_one({'tipo': 'custom'})
            if not doc:
                return jsonify([]), 200
            return jsonify(doc.get('roles', [])), 200
        except Exception as e:
            logging.error(f"Error obteniendo roles custom: {e}")
            return jsonify([]), 200

    @app.route('/roles/custom', methods=['POST'])
    def save_roles_custom():
        try:
            data = request.get_json(silent=True) or []
            mongo.db.roles_custom.update_one(
                {'tipo': 'custom'},
                {'$set': {'tipo': 'custom', 'roles': data}},
                upsert=True,
            )
            return jsonify({'message': 'Roles guardados', 'count': len(data)}), 200
        except Exception as e:
            logging.error(f"Error guardando roles custom: {e}")
            return jsonify({'error': str(e)}), 500
