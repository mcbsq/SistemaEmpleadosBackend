from flask import request
from .logic import (create_educacion, get_educacion_by_empleado, delete_educacion, update_educacion, get_educacion)

# Configurar rutas y funciones para el módulo EDUCACION
def setup_educacion_routes(app, mongo):
    # Ruta para crear datos de educación
    @app.route('/educacion', methods=['POST'])
    def create_educacion_route():
        # Obtener los datos JSON de la solicitud
        data = request.json
        empleado_id = data.get('empleado_id')
        # Llamar a la función create_educacion para crear datos de educación
        return create_educacion(mongo, empleado_id, data)

    # Ruta para obtener datos de educación por ID empleado
    @app.route('/educacion/empleado/<empleado_id>', methods=['GET'])
    def get_educacion_by_empleado_route(empleado_id):
        # Llamar a la función get_educacion_by_empleado para obtener datos de educación por empleado
        return get_educacion_by_empleado(mongo, empleado_id)
    
        # Ruta para obtener todos los datos de red social
    @app.route('/educacion', methods=['GET'])
    def get_educacion_route():
        # Llama a la función lógica para obtener todos los datos de red social
        return get_educacion(mongo)


    # Ruta para eliminar datos de educación por empleado
    @app.route('/educacion/<empleado_id>', methods=['DELETE'])
    def delete_educacion_route(empleado_id):
        # Llamar a la función delete_educacion para eliminar datos de educación por empleado
        return delete_educacion(mongo, empleado_id)

    # Ruta para actualizar datos de educación por empleado
    @app.route('/educacion/<empleado_id>', methods=['PUT'])
    def update_educacion_route(empleado_id):
        # Obtener datos JSON de la solicitud
        data = request.get_json()
        # Llamar a la función update_educacion para actualizar datos de educación por empleado
        return update_educacion(mongo, empleado_id, data)