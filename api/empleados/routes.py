from flask import request
from .logic import (create_empleado, get_empleados, get_empleado, delete_empleado, update_empleado)

# Configurar las rutas para la gestión de empleados
def setup_empleados_routes(app, mongo):
    
    # Ruta para crear un nuevo empleado
    @app.route('/empleados', methods=['POST'])
    def create_empleado_route():
        # Delegamos la extracción del JSON a la función create_empleado
        return create_empleado(mongo)

    # Ruta para obtener todos los empleados
    @app.route('/empleados', methods=['GET'])
    def get_empleados_route():
        return get_empleados(mongo)

    # Ruta para obtener un empleado por su ID
    @app.route('/empleados/<id>', methods=['GET'])
    def get_empleado_route(id):
        return get_empleado(id, mongo)

    # Ruta para actualizar un empleado por su ID
    @app.route('/empleados/<id>', methods=['PUT'])
    def update_empleado_route(id):
        # Delegamos la extracción del JSON y el procesamiento a la función lógica
        return update_empleado(id, mongo)

    # Ruta para eliminar un empleado por su ID
    @app.route('/empleados/<id>', methods=['DELETE'])
    def delete_empleado_route(id):
        return delete_empleado(id, mongo)