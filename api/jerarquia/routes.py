from flask import request, jsonify
from .logic import guardar_jerarquia_logic, obtener_jerarquia_logic

# Esta función configura las rutas HTTP para la jerarquía de empleados
def setup_jerarquia_routes(app, mongo):
    # Define una ruta para guardar o actualizar la jerarquía
    @app.route('/jerarquia', methods=['POST'])
    def guardar_jerarquia_route():
        # Obtiene el JSON enviado con la solicitud
        data = request.get_json()
        # Llama a la función de lógica para guardar la jerarquía con los datos recibidos.
        # Pasa la instancia de Mongo y los datos obtenidos de la solicitud.
        return guardar_jerarquia_logic(mongo, data)

    # Define una ruta para obtener la jerarquía existente
    @app.route('/jerarquia', methods=['GET'])
    def obtener_jerarquia_route():
        # Llama a la función de lógica para obtener la jerarquía.
        # Solo necesita la instancia de Mongo ya que no se requieren datos adicionales.
        return obtener_jerarquia_logic(mongo)
