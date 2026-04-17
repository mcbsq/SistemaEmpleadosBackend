from flask import request, jsonify
import logging
from datetime import datetime

def setup_monitor_routes(app, mongo):

    @app.route('/monitor/incidents', methods=['GET'])
    def get_incidents():
        try:
            docs = list(mongo.db.incidents.find({}).sort('timestamp', -1).limit(200))
            for d in docs:
                d['_id'] = str(d['_id'])
            return jsonify(docs), 200
        except Exception as e:
            logging.error(f"Error obteniendo incidentes: {e}")
            return jsonify([]), 200

    @app.route('/monitor/incidents', methods=['POST'])
    def save_incident():
        try:
            data = request.get_json(silent=True) or {}
            incident = {
                'severity':  data.get('severity', 'error'),
                'message':   data.get('message', ''),
                'endpoint':  data.get('endpoint', ''),
                'status':    data.get('status', ''),
                'timestamp': data.get('timestamp', datetime.utcnow().isoformat()),
            }
            mongo.db.incidents.insert_one(incident)
            return jsonify({'message': 'Incidente guardado'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/monitor/incidents', methods=['DELETE'])
    def clear_incidents():
        try:
            mongo.db.incidents.delete_many({})
            return jsonify({'message': 'Incidentes eliminados'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
