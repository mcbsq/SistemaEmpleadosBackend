# api/validation_utils.py
#
# Helper compartido para no repetir la misma validación de "faltan campos"
# en cada blueprint. Antes, rutas como catalogodepto/comportamientolaboral/
# prestamo usaban request.json['Campo'] directo: si faltaba el campo,
# Flask tronaba con un KeyError sin capturar → 500 con traceback crudo en
# vez de un 400 claro para el frontend.

from flask import jsonify


def require_fields(data, *fields):
    """
    Verifica que todos los `fields` estén presentes en `data` (dict) y no
    sean None. Si falta alguno, regresa una tupla (response, status) lista
    para devolver desde la ruta. Si todo está bien, regresa None.

    Uso:
        data = request.get_json(silent=True) or {}
        error = require_fields(data, 'NombreDepto', 'Descripcion', 'Poblacion')
        if error:
            return error
        # a partir de aquí ya es seguro usar data['NombreDepto'], etc.
    """
    faltantes = [f for f in fields if data.get(f) is None]
    if faltantes:
        return jsonify({
            'error': f"Faltan campos requeridos: {', '.join(faltantes)}"
        }), 400
    return None