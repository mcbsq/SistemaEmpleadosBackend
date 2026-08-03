# api/v1externo/routes.py
# ─────────────────────────────────────────────────────────────────────────────
# Superficie de consumo EXTERNO del sistema: lo que otro programa puede leer
# usando una API key (ver core/apikey_auth.py y api/apikeys/). Solo lectura;
# nunca se expone aquí una ruta de escritura. Reutiliza la misma lógica que
# ya usan las rutas internas (get_empleados, get_rhs, obtener_jerarquia_logic)
# para no duplicar reglas de formato/redacción de datos sensibles.
from flask import jsonify

from core.apikey_auth import require_api_key
from api.empleados.logic import get_empleados
from api.rh.logic import get_rhs
from api.jerarquia.logic import obtener_jerarquia_logic


def setup_v1_externo_routes(app, mongo):

    # Sin scope específico — cualquier API key activa la puede usar para
    # confirmar que la conexión y el header Authorization están bien armados
    # antes de tocar un recurso real. Pensado para pruebas de integración.
    @app.route('/api/v1/ping', methods=['GET'])
    @require_api_key(mongo)
    def v1_ping_route():
        return jsonify({"status": "ok", "message": "API key válida"}), 200

    @app.route('/api/v1/empleados', methods=['GET'])
    @require_api_key(mongo, 'empleados:read')
    def v1_get_empleados_route():
        return get_empleados(mongo)

    @app.route('/api/v1/rh', methods=['GET'])
    @require_api_key(mongo, 'rh:read')
    def v1_get_rh_route():
        return get_rhs(mongo)

    @app.route('/api/v1/organigrama', methods=['GET'])
    @require_api_key(mongo, 'organigrama:read')
    def v1_get_jerarquia_route():
        return obtener_jerarquia_logic(mongo)
