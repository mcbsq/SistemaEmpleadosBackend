# api/expedienteclinico/logic.py
# Los PDFs llegan del frontend como strings base64 (data:application/pdf;base64,...)
# y se guardan directamente en MongoDB — sin sistema de archivos local.
# Esto elimina la dependencia de UPLOAD_FOLDER y funciona en cualquier servidor.

from flask import jsonify
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging


def _serialize(doc):
    if doc is None:
        return None
    doc['_id'] = str(doc['_id'])
    # Datos legacy: algunos documentos guardaron empleado_id como ObjectId en
    # vez de string (inconsistencia de escritura anterior a este código).
    if not isinstance(doc.get('empleado_id'), str):
        doc['empleado_id'] = str(doc['empleado_id'])
    return doc


def create_or_update_expediente(mongo, empleado_id, data):
    """Crea o actualiza el expediente clínico. Upsert por empleado_id."""
    try:
        payload = {
            'empleado_id':             empleado_id,
            'tipoSangre':              data.get('tipoSangre', ''),
            'Padecimientos':           data.get('Padecimientos', ''),
            'NumeroSeguroSocial':      data.get('NumeroSeguroSocial', ''),
            'Segurodegastosmedicos':   data.get('Segurodegastosmedicos',
                                                data.get('Datossegurodegastos', '')),
            # PDF como base64 — puede ser None si no se sube ninguno
            'PDFSegurodegastosmedicos': data.get('PDFSegurodegastosmedicos'),
        }

        result = mongo.db.expedienteclinico.update_one(
            {'empleado_id': empleado_id},
            {'$set': payload},
            upsert=True,
        )

        upserted_id = str(result.upserted_id) if result.upserted_id else None
        return jsonify({
            'message':     'Expediente guardado',
            'upserted_id': upserted_id,
        }), 200
    except Exception as e:
        logging.error(f"Error guardando expediente: {e}")
        return jsonify({'error': str(e)}), 500


def get_all_expedientes(mongo):
    """
    Listado completo para el dashboard de MEDICO (distribución de tipo de
    sangre, cobertura de NSS/seguro, alertas de quién no tiene expediente).
    Excluye el PDF (pesado, no se usa en agregados) — para verlo, el propio
    endpoint por empleado_id sigue siendo la fuente.
    """
    try:
        docs = list(mongo.db.expedienteclinico.find({}, {'PDFSegurodegastosmedicos': 0}))
        return jsonify([_serialize(d) for d in docs]), 200
    except Exception as e:
        logging.error(f"Error listando expedientes: {e}")
        return jsonify({'error': str(e)}), 500


def get_expedienteclinicos_by_empleado(mongo, empleado_id):
    try:
        doc = mongo.db.expedienteclinico.find_one({'empleado_id': empleado_id})
        if not doc:
            return jsonify({}), 200   # vacío pero no 404 — el perfil lo maneja con fallback
        return jsonify(_serialize(doc)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_expedienteclinico(mongo, id):
    try:
        doc = mongo.db.expedienteclinico.find_one({'_id': ObjectId(id)})
        if not doc:
            return jsonify({'error': 'No encontrado'}), 404
        return jsonify(_serialize(doc)), 200
    except (InvalidId, Exception) as e:
        return jsonify({'error': str(e)}), 400


def update_expedienteclinico_empleado(mongo, empleado_id, data):
    return create_or_update_expediente(mongo, empleado_id, data)


def delete_expedienteclinico(mongo, empleado_id):
    try:
        mongo.db.expedienteclinico.delete_one({'empleado_id': empleado_id})
        return jsonify({'message': 'Expediente eliminado'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500