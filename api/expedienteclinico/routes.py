from flask import request, jsonify
from .logic import (create_expediente_clinico, get_expedienteclinicos_by_empleado, get_expedienteclinico, delete_expedienteclinico, update_expedienteclinico_empleado)
from .logic import upload_pdf

# Configuración de las rutas para la gestión de expedientes clínicos
def setup_expedienteclinico_routes(app, mongo):
    @app.route('/expedienteclinico', methods=['POST'])
    def create_expediente_clinico_route():
        # Extraer los datos del expediente clínico de la solicitud JSON
        data = request.form.to_dict(flat=False)
        return create_expediente_clinico(mongo, data)
    
# Configuración de las rutas para la gestión de expedientes clínicos
def setup_expedienteclinico_routes(app, mongo):
    @app.route('/upload_pdf', methods=['POST'])
    def upload_pdf_route():
        return upload_pdf(request, mongo)

    # Ruta para obtener expedientes clínicos por ID de empleado
    @app.route('/expedienteclinico/empleado/<empleado_id>', methods=['GET'])
    def get_expediente_clinicos_by_empleado_route(empleado_id):
        return get_expedienteclinicos_by_empleado(mongo, empleado_id)

    # Ruta para obtener un expediente clínico por su ID
    @app.route('/expedienteclinico/<id>', methods=['GET'])
    def get_expediente_clinico_route(id):
        return get_expedienteclinico(mongo, id)

    # Ruta para eliminar un expediente clínico por ID de empleado
    @app.route('/expedienteclinico/<empleado_id>', methods=['DELETE'])
    def delete_expediente_clinico_route(empleado_id):
        return delete_expedienteclinico(mongo, empleado_id)

    # Ruta para actualizar un expediente clínico por ID de empleado
    @app.route('/expedienteclinico/empleado/<empleado_id>', methods=['PUT'])
    def update_expediente_clinico_empleado_route(empleado_id):
        # Extraer los datos actualizados del expediente clínico de la solicitud JSON
        data = request.get_json()
        return update_expedienteclinico_empleado(mongo, empleado_id, data)