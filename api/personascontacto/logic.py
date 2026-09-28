# api/personascontacto/logic.py
#
# Rediseño: antes cada contacto de emergencia era su propio documento
# (insert_one por contacto, update_one solo tocaba el primero que
# encontrara) — no soportaba más de uno de forma confiable y el PUT de
# actualización pisaba el contacto equivocado si había varios. Ahora, igual
# que redsocial, es UN documento por empleado con un arreglo `Contactos` —
# el frontend manda la lista completa en cada guardado (agregar/quitar es
# solo modificar el arreglo antes de mandarlo).
from flask import jsonify, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def _serializar_contacto(c):
    return {
        'parenstesco':       c.get('parenstesco', ''),
        'nombreContacto':    c.get('nombreContacto', ''),
        'telefonoContacto':  c.get('telefonoContacto', ''),
        'correoContacto':    c.get('correoContacto', ''),
        'direccionContacto': c.get('direccionContacto', ''),
        'whatsappContacto':  c.get('whatsappContacto', ''),
        'telegramContacto':  c.get('telegramContacto', ''),
        'facebookContacto':  c.get('facebookContacto', ''),
    }


def get_personascontacto_by_empleado(mongo, empleadoid):
    try:
        eid = ObjectId(empleadoid)
    except (InvalidId, Exception):
        return jsonify({'error': 'Invalid ObjectId'}), 400
    try:
        doc = mongo.db.personascontacto.find_one({'empleadoid': eid})
        contactos = [_serializar_contacto(c) for c in (doc.get('Contactos', []) if doc else [])]
        return jsonify({'Contactos': contactos}), 200
    except Exception as e:
        logger.error(f"Error en get_personascontacto_by_empleado: {e}")
        return jsonify({'error': str(e)}), 500


def get_personascontactos(mongo):
    try:
        docs = list(mongo.db.personascontacto.find())
        empleados = {str(e['_id']): f"{e.get('Nombre','')} {e.get('ApelPaterno','')} {e.get('ApelMaterno','')}"
                     for e in mongo.db.empleados.find()}
        for d in docs:
            d['NombreCompleto'] = empleados.get(str(d.get('empleadoid', '')), '')
        return Response(json_util.dumps(docs), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def delete_personascontacto(mongo, empleadoid):
    try:
        eid = ObjectId(empleadoid)
    except (InvalidId, Exception):
        return jsonify({'error': 'Invalid ObjectId'}), 400
    try:
        result = mongo.db.personascontacto.delete_one({'empleadoid': eid})
        if result.deleted_count > 0:
            return jsonify({'message': f'Contactos de {empleadoid} eliminados'}), 200
        return jsonify({'message': 'No encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_personascontacto_by_empleado(mongo, empleadoid, contactos_nuevos):
    """
    Reemplaza la lista completa de contactos de emergencia de un empleado.
    `contactos_nuevos` es un arreglo (puede venir vacío — borrar todos es
    válido). Ya no exige nombreContacto/parenstesco a nivel global: se
    valida por contacto individual, así uno incompleto no tumba el resto.
    """
    try:
        eid = ObjectId(empleadoid)
    except (InvalidId, Exception):
        return jsonify({'error': 'Invalid ObjectId'}), 400

    if not isinstance(contactos_nuevos, list):
        return jsonify({'error': 'Contactos debe ser una lista'}), 400

    limpios = []
    for c in contactos_nuevos:
        nombre = (c or {}).get('nombreContacto', '').strip()
        parentesco = (c or {}).get('parenstesco', '').strip()
        if not nombre or not parentesco:
            continue  # contacto incompleto — se omite en vez de tronar el guardado
        limpios.append(_serializar_contacto(c))

    mongo.db.personascontacto.update_one(
        {'empleadoid': eid},
        {'$set': {'empleadoid': eid, 'Contactos': limpios}},
        upsert=True,
    )
    return jsonify({'message': f'Contactos actualizados para empleado {empleadoid}', 'Contactos': limpios}), 200
