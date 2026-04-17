# api/rh/logic.py
from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def _serialize(doc):
    if not doc:
        return None
    doc['_id']         = str(doc['_id'])
    doc['empleado_id'] = str(doc['empleado_id'])
    return doc


# ── GET todos ─────────────────────────────────────────────────────────────────
def get_rhs(mongo):
    try:
        rh_list = list(mongo.db.rh.find())
        empleados = {str(e['_id']): f"{e.get('Nombre','')} {e.get('ApelPaterno','')} {e.get('ApelMaterno','')}"
                     for e in mongo.db.empleados.find()}
        for doc in rh_list:
            doc['NombreCompleto'] = empleados.get(str(doc.get('empleado_id', '')), '')
        return Response(json_util.dumps(rh_list), mimetype="application/json")
    except Exception as e:
        logger.error(f"Error en get_rhs: {e}")
        return jsonify({'error': str(e)}), 500


# ── GET por empleado ──────────────────────────────────────────────────────────
def get_rh_by_empleado_id(mongo, empleado_id):
    try:
        doc = mongo.db.rh.find_one({'empleado_id': ObjectId(empleado_id)})
        if not doc:
            return jsonify({}), 200   # vacío → el perfil usa fallback, no rompe
        return jsonify(_serialize(doc)), 200
    except (InvalidId, Exception) as e:
        return jsonify({'error': str(e)}), 500


# ── CREATE ────────────────────────────────────────────────────────────────────
def create_rh(mongo, empleado_id, rh_data):
    if not request.is_json:
        return jsonify({'error': 'No data provided'}), 400
    try:
        data = request.get_json()
        eid  = ObjectId(data.get('empleado_id', empleado_id))

        payload = _build_payload(eid, data)
        result  = mongo.db.rh.insert_one(payload)

        return jsonify({'_id': str(result.inserted_id), 'message': 'RH creado'}), 201
    except Exception as e:
        logger.error(f"Error en create_rh: {e}")
        return jsonify({'error': str(e)}), 500


# ── UPDATE — upsert real ──────────────────────────────────────────────────────
# FIX PRINCIPAL:
#   · El original hacía find_one primero y devolvía 404 si no existía.
#     Eso hacía que el primer guardado desde el perfil siempre fallara.
#   · Ahora usa update_one con upsert=True → crea el documento si no existe.
#   · El PDF (ExpedienteDigitalPDF) puede llegar como array de use-file-picker
#     [{content: "data:...", name: "..."}] — se normaliza antes de guardar.
def update_rh(mongo, empleado_id, rh_data):
    try:
        data = request.get_json(silent=True) or {}
        eid  = ObjectId(empleado_id)

        payload = _build_payload(eid, data)

        mongo.db.rh.update_one(
            {'empleado_id': eid},
            {'$set': payload},
            upsert=True,         # ← crea si no existe, actualiza si existe
        )

        return jsonify({'message': f'RH actualizado para empleado {empleado_id}'}), 200

    except (InvalidId, Exception) as e:
        logger.error(f"Error en update_rh: {e}")
        return jsonify({'error': str(e)}), 500


# ── DELETE ────────────────────────────────────────────────────────────────────
def delete_rh_by_empleado_id(mongo, empleado_id):
    try:
        result = mongo.db.rh.delete_one({'empleado_id': ObjectId(empleado_id)})
        if result.deleted_count > 0:
            return jsonify({'message': f'RH eliminado para empleado {empleado_id}'}), 200
        return jsonify({'error': 'No encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Helper interno ────────────────────────────────────────────────────────────
def _build_payload(eid, data):
    """Construye el documento a guardar normalizando el PDF."""

    # El PDF puede llegar como:
    #   · string base64/data-URL  (guardado desde MongoDB)
    #   · array [{content: "data:...", name: "..."}]  (use-file-picker)
    #   · None / ""
    pdf_raw = data.get('ExpedienteDigitalPDF')
    if isinstance(pdf_raw, list) and len(pdf_raw) > 0:
        first = pdf_raw[0]
        pdf   = first.get('content') or first if isinstance(first, dict) else first
    else:
        pdf = pdf_raw or None

    return {
        'empleado_id':        eid,
        'Puesto':             data.get('Puesto',             ''),
        'JefeInmediato':      data.get('JefeInmediato',      ''),
        'JefeInmediato_id':   data.get('JefeInmediato_id',   ''),
        'HorarioLaboral':     data.get('HorarioLaboral',     {
            'HoraEntrada':    '',
            'HoraSalida':     '',
            'TiempoComida':   '',
            'DiasTrabajados': '',
        }),
        'NombreCompleto':     data.get('NombreCompleto',     ''),
        'ExpedienteDigitalPDF': pdf,
    }