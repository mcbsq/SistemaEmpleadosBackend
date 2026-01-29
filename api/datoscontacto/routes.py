from flask import request, jsonify
from .logic import create_datoscontacto, get_datoscontacto_by_empleado, get_datoscontactos, delete_datoscontacto, update_datoscontacto
from .logic import guardar_coordenadas_en_db

# Configurar rutas y funciones para el módulo DATOS CONTACTO
def setup_datoscontacto_routes(app, mongo):
    # Ruta para crear datos de contacto
    @app.route('/datoscontacto', methods=['POST'])
    def create_datoscontacto_route():
        # Obtener datos del cuerpo de la solicitud HTTP, con valores por defecto en caso de ausencia
        TelFijo = request.json.get('TelFijo', '')
        TelCelular = request.json.get('TelCelular', '')
        IdWhatsApp = request.json.get('IdWhatsApp', '')
        IdTelegram = request.json.get('IdTelegram', '')
        ListaCorreos = request.json.get('ListaCorreos', '')
        EmpleadoId = request.json.get('empleado_id', '')
        # Llamar a la función create_datoscontacto para crear datos de contacto
        return create_datoscontacto(mongo, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos, EmpleadoId)

    # Ruta para guardar coordenadas en la base de datos
    @app.route('/guardar-coordenadas', methods=['POST'])
    def guardar_coordenadas():
        data = request.json
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        # Aquí deberías llamar a la función para guardar las coordenadas en la base de datos
        guardar_coordenadas_en_db(mongo, latitude, longitude)
        return jsonify({'message': 'Coordenadas guardadas correctamente'}), 200
        return app
    
    # Ruta para obtener datos de contacto por ID de empleado
    @app.route('/datoscontacto/empleado/<empleado_id>', methods=['GET'])
    def get_datoscontacto_by_empleado_route(empleado_id):
        # Llamar a la función get_datoscontacto_by_empleado para obtener datos de contacto por ID de empleado
        return get_datoscontacto_by_empleado(mongo, empleado_id)

    # Ruta para obtener todos los datos de contacto
    @app.route('/datoscontacto', methods=['GET'])
    def get_datoscontactos_route():
        # Llamar a la función get_datoscontactos para obtener todos los datos de contacto
        return get_datoscontactos(mongo)

    # Ruta para eliminar datos de contacto por ID
    @app.route('/datoscontacto/<id>', methods=['DELETE'])
    def delete_datoscontacto_route(id):
        # Llamar a la función delete_datoscontacto para eliminar datos de contacto por ID
        return delete_datoscontacto(mongo, id)

    # Ruta para actualizar datos de contacto por ID de empleado
    @app.route('/datoscontacto/empleado/<empleado_id>', methods=['PUT'])
    def update_datoscontacto_route(empleado_id):
        # Obtener nuevos datos del cuerpo de la solicitud HTTP, con valores por defecto en caso de ausencia
        TelFijo = request.json.get('TelFijo', '')
        TelCelular = request.json.get('TelCelular', '')
        IdWhatsApp = request.json.get('IdWhatsApp', '')
        IdTelegram = request.json.get('IdTelegram', '')
        ListaCorreos = request.json.get('ListaCorreos', '')
        # Llamar a la función update_datoscontacto para actualizar datos de contacto por ID de empleado
        return update_datoscontacto(mongo, empleado_id, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos)