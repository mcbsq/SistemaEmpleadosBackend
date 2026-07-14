from flask import request, jsonify
import logging
from datetime import datetime
from api.auth_decorators import require_roles


def setup_monitor_routes(app, mongo):

    @app.route('/monitor/incidents', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_incidents():
        try:
            docs = list(mongo.db.incidents.find({}).sort('timestamp', -1).limit(200))
            for d in docs:
                d['_id'] = str(d['_id'])
            return jsonify(docs), 200
        except Exception as e:
            logging.error(f"Error obteniendo incidentes: {e}")
            return jsonify([]), 200

    # A propósito SIN autenticación: si esto reporta errores del cliente
    # (incluida la pantalla de login, antes de tener token), protegerlo
    # rompería ese reporte. Si no es tu caso, dime y lo cierro también.
    @app.route('/monitor/incidents', methods=['POST'])
    def save_incident():
        try:
            data = request.get_json(silent=True) or {}
            incident = {
                'severity':  data.get('severity', 'error'),
                'categoria': data.get('categoria', 'api'),
                'message':   (data.get('message') or '')[:500],
                'endpoint':  (data.get('endpoint') or '')[:300],
                'method':    data.get('method', ''),
                'status':    data.get('status', ''),
                'role':      data.get('role', ''),
                'timestamp': data.get('timestamp', datetime.utcnow().isoformat()),
            }
            mongo.db.incidents.insert_one(incident)
            return jsonify({'message': 'Incidente guardado'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # Borrar el historial de incidentes sí queda restringido: podría usarse
    # para tapar evidencia de un problema o de un ataque en curso.
    @app.route('/monitor/incidents', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def clear_incidents():
        try:
            mongo.db.incidents.delete_many({})
            return jsonify({'message': 'Incidentes eliminados'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500