from flask import request, Response
from .logic import (create_or_update_redsocial, get_redessociales_empleado, delete_redsocial, update_redessociales_empleado, get_redsocial)

# Esta función configura las rutas para manejar las redes sociales de los empleados
def setup_redsocial_routes(app, mongo):
    # Ruta para crear o actualizar las redes sociales de un empleado
    @app.route('/redsocial', methods=['POST'])
    def create_or_update_redsocial_route():
        # Obtiene los datos enviados en la solicitud.
        data = request.get_json()
        empleado_id = data.get('empleado_id')
        redes_sociales = data.get('RedesSociales', [])
        # Llama a la función correspondiente en el módulo de lógica
        return create_or_update_redsocial(mongo, empleado_id, redes_sociales)

    # Ruta para obtener todos los datos de red social
    @app.route('/redsocial', methods=['GET'])
    def get_redsocial_route():
        # Llama a la función lógica para obtener todos los datos de red social
        return get_redsocial(mongo)

    # Ruta para obtener las redes sociales de un empleado específico
    @app.route('/redsocial/empleado/<empleado_id>', methods=['GET'])
    def get_redessociales_empleado_route(empleado_id):
        # Llama a la función en el módulo de lógica para obtener las redes sociales del empleado
        return get_redessociales_empleado(mongo, empleado_id)

    # Ruta para eliminar las redes sociales de un empleado específico
    @app.route('/redsocial/<empleado_id>', methods=['DELETE'])
    def delete_redsocial_route(empleado_id):
        # Llama a la función en el módulo de lógica para eliminar las redes sociales del empleado
        return delete_redsocial(mongo, empleado_id)

    # Ruta para actualizar las redes sociales de un empleado específico
    @app.route('/redsocial/empleado/<empleado_id>', methods=['PUT'])
    def update_redessociales_empleado_route(empleado_id):
        # Obtiene las nuevas redes sociales enviadas en la solicitud
        redes_sociales_nuevas = request.get_json().get('RedesSociales', [])
        # Llama a la función en el módulo de lógica para actualizar las redes sociales del empleado
        return update_redessociales_empleado(mongo, empleado_id, redes_sociales_nuevas)
