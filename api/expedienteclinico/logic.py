from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
import os

def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

######################################################

#EXPEDIENTE CLINICO
# Cada función a continuación corresponde a un endpoint en tu API.

# Crea un nuevo expediente clínico en la base de datos.
def create_expediente_clinico(mongo, data, app):
    try:
        # Extraer datos del expediente clínico de la solicitud JSON
        empleado_id = data.get('empleado_id')
        tipo_sangre = data.get('tipoSangre')
        padecimientos = data.get('Padecimientos')
        num_ss = data.get('NumeroSeguroSocial')
        datos_seguro_gastos = data.get('Datossegurodegastos')

        # Manejar la carga de archivos PDF
        pdf_files = []
        for key in request.files:
            pdf_file = request.files[key]
            filename = secure_filename(pdf_file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            pdf_file.save(file_path)
            pdf_files.append({
                'name': filename,
                'path': file_path
            })

        # Insertar datos del expediente clínico en la base de datos
        expediente_clinico_data = {
            'empleado_id': empleado_id,
            'tipoSangre': tipo_sangre,
            'Padecimientos': padecimientos,
            'NumeroSeguroSocial': num_ss,
            'Datossegurodegastos': datos_seguro_gastos,
            'PDFSegurodegastosmedicos': pdf_files
        }
        mongo.db.expedienteclinico.insert_one(expediente_clinico_data)

        # Devolver una respuesta de éxito
        return jsonify({'message': 'Expediente clínico creado exitosamente'}), 201

    except Exception as e:
        print(f'Error: {e}')
        return jsonify({'error': 'Error interno del servidor'}), 500
    
def upload_pdf(app, request, mongo):
    try:
        if 'pdf' not in request.files:
            return jsonify({'error': 'No PDF provided'}), 400

        pdf_files = request.files.getlist('pdf')
        uploaded_files = []

        for pdf in pdf_files:
            if pdf.filename == '':
                return jsonify({'error': 'No selected file'}), 400
            if pdf:
                filename = secure_filename(pdf.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                pdf.save(file_path)
                uploaded_files.append(file_path)

        return jsonify({'message': 'PDFs uploaded successfully', 'files': uploaded_files}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Obtiene los expedientes clínicos por ID de empleado.
def get_expedienteclinicos_by_empleado(mongo, empleado_id):
    try:
        # Busca todos los expedientes clínicos asociados a un empleado.
        expedienteclinicoss = mongo.db.expedienteclinico.find({'empleado_id': ObjectId(empleado_id)})

        # Devuelve los resultados como JSON
        response = json_util.dumps(expedienteclinicoss)
        return Response(response, mimetype="application/json")

    # Si ocurre un error durante la consulta, captúralo y devuelve un mensaje de error.
    except Exception as e:
        print(f'Error: {e}')
        return jsonify({'error': 'Internal server error'}), 500

# Obtiene un solo expediente clínico por su ID.
def get_expedienteclinico(mongo,id):
    # Busca el expediente clínico en la base de datos y devuelve el resultado.
    print(id)
    expedienteclinico = mongo.db.expedienteclinico.find_one({'_id': ObjectId(id), })
    response = json_util.dumps(expedienteclinico)
    return Response(response, mimetype="application/json")

# Elimina un expediente clínico basado en el ID del empleado.
def delete_expedienteclinico(mongo, empleado_id):
    try:
        # Convierte el empleado_id a ObjectId 
        object_id = ObjectId(empleado_id)
        # Realiza la eliminación en la colección expedienteclinico
        result = mongo.db.expedienteclinico.delete_many({'empleado_id': object_id})
        # Devuelve un mensaje indicando si la eliminación fue exitosa o no
        if result.deleted_count > 0:
            response = jsonify({'message': 'Expediente Clinico for empleado ' + empleado_id + ' deleted successfully'})
            response.status_code = 200
        else:
            response = jsonify({'message': 'No Expediente Clinico found for empleado ' + empleado_id})
            response.status_code = 404

    except Exception as e:
        response = jsonify({'error': str(e)})
        response.status_code = 500

    return response

# Actualiza la información de un expediente clínico
def update_expedienteclinico_empleado(mongo, empleado_id, data):
    try:
        # Busca el expediente clínico actual y actualízalo con los nuevos datos
        empleado_id_obj = ObjectId(empleado_id)
        data = request.get_json()
        expediente_clinico_nuevo = data  # Ahora asumimos que recibes el objeto directamente

        existing_data = mongo.db.expedienteclinico.find_one({'empleado_id': empleado_id_obj})

        if existing_data:
            mongo.db.expedienteclinico.update_one(
                {'empleado_id': empleado_id_obj},
                {
                    '$set': {
                        'tipoSangre': expediente_clinico_nuevo.get('tipoSangre'),
                        'Padecimientos': expediente_clinico_nuevo.get('Padecimientos'),
                        'NumeroSeguroSocial': expediente_clinico_nuevo.get('NumeroSeguroSocial'),
                        'Segurodegastosmedicos': expediente_clinico_nuevo.get('Segurodegastosmedicos'),
                        'PDFSegurodegastosmedicos': expediente_clinico_nuevo.get('PDFSegurodegastosmedicos'),
                    }
                }
            )

            response = jsonify({
                'empleado_id': str(empleado_id_obj),
                'message': 'Datos de expediente clínico actualizados exitosamente'
            })
            response.status_code = 200
            return response
        else:
            # Si no se encuentra el expediente, crea uno nuevo
            result = mongo.db.expedienteclinico.insert_one({
                'empleado_id': empleado_id_obj,
                'tipoSangre': expediente_clinico_nuevo.get('tipoSangre'),
                'Padecimientos': expediente_clinico_nuevo.get('Padecimientos'),
                'NumeroSeguroSocial': expediente_clinico_nuevo.get('NumeroSeguroSocial'),
                'Segurodegastosmedicos': expediente_clinico_nuevo.get('Segurodegastosmedicos'),
                'PDFSegurodegastosmedicos': expediente_clinico_nuevo.get('PDFSegurodegastosmedicos'),
            })
            print(f'Resultado de la inserción en la base de datos: {result.inserted_id}')

            response = jsonify({
                'empleado_id': str(empleado_id_obj),
                'message': 'Datos de expediente clínico creados exitosamente'
            })
            response.status_code = 201
            return response

    except Exception as e:
        print("Error:", e)
        return jsonify({'message': 'Error al actualizar expediente clínico del empleado'}), 500
    
########################################################
def not_found(error=None):
    message = {
        'message': 'Resource Not Found: ' + request.url,
        'status': 404
    }
    response = jsonify(message)
    response.status_code = 404
    return response