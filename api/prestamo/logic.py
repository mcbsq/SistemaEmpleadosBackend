# api/prestamo/logic.py
from flask import jsonify, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def _to_object_id(id_str):
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return None


# empleado_id es opcional por ahora (compatibilidad con el frontend actual,
# que todavía no lo manda). Recomendado hacerlo obligatorio en cuanto el
# frontend lo envíe — un préstamo sin dueño no sirve de mucho.
def create_prestamo(mongo, MontoPrestamo, TasaInteres, FecSolicitud, FecAprobacion,
                     FecVencimiento, PlazoMeses, MontoPendiente, PagosRealizados,
                     CuotaMensual, MetodoPago, empleado_id=None):
    try:
        doc = {
            'MontoPrestamo':   MontoPrestamo,
            'TasaInteres':     TasaInteres,
            'FecSolicitud':    FecSolicitud,
            'FecAprobacion':   FecAprobacion,
            'FecVencimiento':  FecVencimiento,
            'PlazoMeses':      PlazoMeses,
            'MontoPendiente':  MontoPendiente,
            'PagosRealizados': PagosRealizados,
            'CuotaMensual':    CuotaMensual,
            'MetodoPago':      MetodoPago,
        }
        if empleado_id:
            eid = _to_object_id(empleado_id)
            if eid is None:
                return jsonify({'error': 'empleado_id inválido'}), 400
            doc['empleado_id'] = eid

        # FIX: antes se guardaba str(insert_one_result) en vez de
        # str(insert_one_result.inserted_id) — el _id devuelto al frontend
        # no era un ObjectId real utilizable.
        result = mongo.db.prestamo.insert_one(doc)
        doc['_id'] = str(result.inserted_id)
        if empleado_id:
            doc['empleado_id'] = empleado_id
        return jsonify(doc), 201
    except Exception as e:
        logger.error(f"Error en create_prestamo: {e}")
        return jsonify({'error': str(e)}), 500


def get_prestamos(mongo):
    try:
        prestamos = mongo.db.prestamo.find()
        return Response(json_util.dumps(prestamos), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_prestamos_by_empleado(mongo, empleado_id):
    eid = _to_object_id(empleado_id)
    if eid is None:
        return jsonify({'error': 'empleado_id inválido'}), 400
    try:
        prestamos = mongo.db.prestamo.find({'empleado_id': eid})
        return Response(json_util.dumps(prestamos), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_prestamo(mongo, id):
    eid = _to_object_id(id)
    if eid is None:
        return jsonify({'error': 'ID inválido'}), 400
    try:
        prestamo = mongo.db.prestamo.find_one({'_id': eid})
        if not prestamo:
            return jsonify({'message': 'Préstamo no encontrado'}), 404
        return Response(json_util.dumps(prestamo), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def delete_prestamo(mongo, id):
    eid = _to_object_id(id)
    if eid is None:
        return jsonify({'error': 'ID inválido'}), 400
    try:
        result = mongo.db.prestamo.delete_one({'_id': eid})
        if result.deleted_count > 0:
            return jsonify({'message': f'Préstamo {id} eliminado exitosamente'}), 200
        return jsonify({'message': 'No se encontró el préstamo para eliminar'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_prestamo(mongo, _id, MontoPrestamo, TasaInteres, FecSolicitud, FecAprobacion,
                     FecVencimiento, PlazoMeses, MontoPendiente, PagosRealizados,
                     CuotaMensual, MetodoPago):
    eid = _to_object_id(_id)
    if eid is None:
        return jsonify({'error': 'ID inválido'}), 400
    try:
        mongo.db.prestamo.update_one({'_id': eid}, {'$set': {
            'MontoPrestamo':   MontoPrestamo,
            'TasaInteres':     TasaInteres,
            'FecSolicitud':    FecSolicitud,
            'FecAprobacion':   FecAprobacion,
            'FecVencimiento':  FecVencimiento,
            'PlazoMeses':      PlazoMeses,
            'MontoPendiente':  MontoPendiente,
            'PagosRealizados': PagosRealizados,
            'CuotaMensual':    CuotaMensual,
            'MetodoPago':      MetodoPago,
        }})
        return jsonify({'message': f'Préstamo {_id} actualizado exitosamente'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500