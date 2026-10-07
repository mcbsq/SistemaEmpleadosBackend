import re
from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def _serialize(doc):
    if not doc:
        return None
    doc['_id'] = str(doc['_id'])
    if doc.get('empleado_id') and not isinstance(doc['empleado_id'], str):
        doc['empleado_id'] = str(doc['empleado_id'])
    return doc


ETIQUETAS = {
    'Calle': 'la calle', 'NumExterior': 'el número exterior (o "S/N")', 'NumInterior': 'el número interior',
    'Colonia': 'la colonia', 'Manzana': 'la manzana', 'Lote': 'el lote', 'Municipio': 'el municipio',
    'Ciudad': 'la ciudad o estado', 'CodigoP': 'el código postal',
}


def validar_direccion(mongo, data, antes=None):
    """Campos obligatorios según la configuración de la empresa. Si el
    domicilio no cambió, no se valida (no bloquear al editar otra cosa)."""
    from api.org.logic import get_campos_direccion
    if antes is not None and all(str(data.get(k) or '') == str(antes.get(k) or '') for k in ETIQUETAS):
        return {}
    errores = {}
    for campo, regla in get_campos_direccion(mongo).items():
        if regla == 'obligatorio' and not str(data.get(campo) or '').strip():
            errores[campo] = f'Falta {ETIQUETAS.get(campo, campo)}.'
    cp = str(data.get('CodigoP') or '').strip()
    if cp and not re.fullmatch(r'\d{5}', cp):
        errores['CodigoP'] = 'El código postal tiene 5 dígitos.'
    return errores


def create_direccion(mongo):
    try:
        data = request.json
        if not data:
            return jsonify({'message': 'No se recibieron datos'}), 400
        errores = validar_direccion(mongo, data)
        if errores:
            return jsonify({'error': 'Completa el domicilio.', 'campos': errores}), 400

        id_insertado = mongo.db.direccion.insert_one({
            'Calle':       data.get('Calle'),
            'NumExterior': data.get('NumExterior'),
            'NumInterior': data.get('NumInterior'),
            'Manzana':     data.get('Manzana'),
            'Lote':        data.get('Lote'),
            'Colonia':     data.get('Colonia'),
            'Municipio':   data.get('Municipio'),
            'Ciudad':      data.get('Ciudad'),
            'CodigoP':     data.get('CodigoP'),
            'Pais':        data.get('Pais', 'México'),
            'empleado_id': data.get('empleado_id'),
            'lat':         data.get('lat', None),
            'lng':         data.get('lng', None),
        }).inserted_id

        return jsonify({
            '_id':     str(id_insertado),
            'message': 'Dirección creada con éxito'
        }), 201

    except Exception as e:
        logger.error(f"Error en create_direccion: {e}")
        return jsonify({'error': str(e)}), 500


def get_direccions(mongo):
    try:
        direccions = list(mongo.db.direccion.find())
        return Response(json_util.dumps(direccions), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_direccion(mongo, id):
    try:
        obj_id = ObjectId(id)
    except (InvalidId, TypeError):
        return jsonify({'error': 'ID inválido'}), 400
    try:
        doc = mongo.db.direccion.find_one({'_id': obj_id})
        if not doc:
            return jsonify({'message': 'Dirección no encontrada'}), 404
        return Response(json_util.dumps(doc), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_direccion_by_empleado(mongo, empleado_id):
    """GET /direccion/empleado/<empleado_id> — usado por el frontend en Perfil.js"""
    try:
        # Buscar por empleado_id como string (como lo guarda create_direccion)
        doc = mongo.db.direccion.find_one({'empleado_id': empleado_id})

        # Fallback: buscar como ObjectId por si hay docs viejos guardados así
        if not doc:
            try:
                doc = mongo.db.direccion.find_one({'empleado_id': ObjectId(empleado_id)})
            except (InvalidId, TypeError):
                pass

        if not doc:
            return jsonify({}), 200

        return jsonify(_serialize(doc)), 200

    except Exception as e:
        logger.error(f"Error en get_direccion_by_empleado: {e}")
        return jsonify({'error': str(e)}), 500


def update_direccion(mongo, id):
    """PUT /direccion/<id> — actualiza por _id (ruta original)"""
    try:
        obj_id = ObjectId(id)
    except (InvalidId, TypeError):
        return jsonify({'error': 'ID inválido'}), 400
    try:
        data = request.json or {}
        mongo.db.direccion.update_one({'_id': obj_id}, {'$set': data})
        return jsonify({'message': 'Actualizado con éxito'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_direccion_by_empleado(mongo, empleado_id):
    """
    PUT /direccion/empleado/<empleado_id>
    Usado por Perfil.js para guardar cambios incluyendo lat/lng.
    Upsert: crea el documento si no existe.
    """
    try:
        data = request.json or {}
        antes = mongo.db.direccion.find_one({'empleado_id': empleado_id}) or {}
        errores = validar_direccion(mongo, data, antes)
        if errores:
            return jsonify({'error': 'Completa el domicilio.', 'campos': errores}), 400

        payload = {
            'Calle':       data.get('Calle',       ''),
            'NumExterior': data.get('NumExterior',  ''),
            'NumInterior': data.get('NumInterior',  ''),
            'Manzana':     data.get('Manzana',      ''),
            'Lote':        data.get('Lote',         ''),
            'Colonia':     data.get('Colonia',      ''),
            'Municipio':   data.get('Municipio',    ''),
            'Ciudad':      data.get('Ciudad',       ''),
            'CodigoP':     data.get('CodigoP',      ''),
            'Pais':        data.get('Pais',         'México'),
            'empleado_id': empleado_id,
            # Guardar coordenadas solo si vienen — no pisar con None si ya existen
            **({'lat': data['lat']}  if 'lat' in data else {}),
            **({'lng': data['lng']}  if 'lng' in data else {}),
        }

        mongo.db.direccion.update_one(
            {'empleado_id': empleado_id},
            {'$set': payload},
            upsert=True
        )
        return jsonify({'message': f'Dirección actualizada para empleado {empleado_id}'}), 200

    except Exception as e:
        logger.error(f"Error en update_direccion_by_empleado: {e}")
        return jsonify({'error': str(e)}), 500


def delete_direccion(mongo, id):
    try:
        obj_id = ObjectId(id)
    except (InvalidId, TypeError):
        return jsonify({'error': 'ID inválido'}), 400
    try:
        mongo.db.direccion.delete_one({'_id': obj_id})
        return jsonify({'message': f'Direccion {id} eliminada'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500