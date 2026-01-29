from flask import request
from .logic import (create_rh, get_rhs, get_rh_by_empleado_id, delete_rh_by_empleado_id, update_rh)

# Esta función establece las rutas para la gestión de la información de RH de los empleados.
def setup_rh_routes(app, mongo):
    # Ruta para crear información de RH para un empleado.
    @app.route('/rh', methods=['POST'])
    def create_rh_route():
        # Obtiene los datos de la solicitud.
        data = request.get_json()
        empleado_id = data.get('empleado_id')  # ID del empleado.
        # Llama a la función correspondiente en el módulo de lógica para crear la información de RH.
        return create_rh(mongo, empleado_id, data)

    # Ruta para obtener la información de RH de todos los empleados.
    @app.route('/rh', methods=['GET'])
    def get_rhs_route():
        # Llama a la función en el módulo de lógica para obtener la información de todos los empleados.
        return get_rhs(mongo)

    # Ruta para obtener la información de RH de un empleado específico por su ID.
    @app.route('/rh/<empleado_id>', methods=['GET'])
    def get_rh_by_empleado_id_route(empleado_id):
        # Llama a la función en el módulo de lógica para obtener la información de RH del empleado especificado.
        return get_rh_by_empleado_id(mongo, empleado_id)

    # Ruta para eliminar la información de RH de un empleado específico por su ID.
    @app.route('/rh/<empleado_id>', methods=['DELETE'])
    def delete_rh_by_empleado_id_route(empleado_id):
        # Llama a la función en el módulo de lógica para eliminar la información de RH del empleado especificado.
        return delete_rh_by_empleado_id(mongo, empleado_id)

    # Ruta para actualizar la información de RH de un empleado específico por su ID.
    @app.route('/rh/<empleado_id>', methods=['PUT'])
    def update_rh_route(empleado_id):
        # Obtiene los datos actualizados de la solicitud.
        update_data = request.get_json()
        # Llama a la función en el módulo de lógica para actualizar la información de RH del empleado especificado.
        return update_rh(mongo, empleado_id, update_data)
