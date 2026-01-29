from flask import request
from .logic import (create_personascontacto, get_personascontactos, get_personascontacto_by_empleado, delete_personascontacto, update_personascontacto_by_empleado)

# Esta función establece las rutas para las operaciones CRUD de personas de contacto.
def setup_personascontacto_routes(app, mongo):
    # Ruta para crear una nueva persona de contacto.
    @app.route('/personascontacto', methods=['POST'])
    def create_personascontacto_route():
        # Obtiene la información de la persona de contacto desde el cuerpo de la solicitud.
        personalcontacto = request.json.get('personalcontacto', {})
        # Llama a la función lógica para crear una nueva persona de contacto.
        return create_personascontacto(mongo, personalcontacto)

    # Ruta para obtener todas las personas de contacto.
    @app.route('/personascontacto', methods=['GET'])
    def get_personascontactos_route():
        # Llama a la función lógica para obtener todas las personas de contacto.
        return get_personascontactos(mongo)

    # Ruta para obtener personas de contacto por ID de empleado.
    @app.route('/personascontacto/empleado/<empleadoid>', methods=['GET'])
    def get_personascontacto_by_empleado_route(empleadoid):
        # Llama a la función lógica para obtener personas de contacto específicas de un empleado.
        return get_personascontacto_by_empleado(mongo, empleadoid)

    # Ruta para eliminar una persona de contacto por ID de empleado.
    @app.route('/personascontacto/<empleadoid>', methods=['DELETE'])
    def delete_personascontacto_route(empleadoid):
        # Llama a la función lógica para eliminar la persona de contacto de un empleado.
        return delete_personascontacto(mongo, empleadoid)

    # Ruta para actualizar la información de la persona de contacto de un empleado.
    @app.route('/personascontacto/empleado/<empleadoid>', methods=['PUT'])
    def update_personascontacto_by_empleado_route(empleadoid):
        # Obtiene la información actualizada de la persona de contacto desde el cuerpo de la solicitud.
        personal_contacto = request.json.get('personalcontacto', {})
        # Llama a la función lógica para actualizar la persona de contacto de un empleado.
        return update_personascontacto_by_empleado(mongo, empleadoid, personal_contacto)
