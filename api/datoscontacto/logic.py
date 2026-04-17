# api/datoscontacto/logic.py
from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def create_datoscontacto(mongo, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos, empleado_id):
    try:
        TelFijo      = request.json.get('TelFijo', None)
        TelCelular   = request.json.get('TelCelular', None)
        IdWhatsApp   = request.json.get('IdWhatsApp', None)
        IdTelegram   = request.json.get('IdTelegram', None)
        ListaCorreos = request.json.get('ListaCorreos', None)

        result = mongo.db.datoscontacto.insert_one({
            'EmpleadoId':   ObjectId(empleado_id),
            'TelFijo':      TelFijo,
            'TelCelular':   TelCelular,
            'IdWhatsApp':   IdWhatsApp,
            'IdTelegram':   IdTelegram,
            'ListaCorreos': ListaCorreos,
        })

        return jsonify({
            '_id':          str(result.inserted_id),   # ← fix: era str(id)
            'EmpleadoId':   empleado_id,
            'TelFijo':      TelFijo,
            'TelCelular':   TelCelular,
            'IdWhatsApp':   IdWhatsApp,
            'IdTelegram':   IdTelegram,
            'ListaCorreos': ListaCorreos,
        }), 201

    except Exception as e:
        logger.error(f"Error en create_datoscontacto: {e}")
        return jsonify({'error': str(e)}), 500


def get_datoscontacto_by_empleado(mongo, empleado_id):
    try:
        doc = mongo.db.datoscontacto.find_one({'EmpleadoId': ObjectId(empleado_id)})
        if not doc:
            return jsonify({}), 200   # vacío, el perfil usa fallback
        return jsonify({
            "_id":          str(doc["_id"]),
            "EmpleadoId":   str(doc["EmpleadoId"]),
            "TelFijo":      doc.get("TelFijo"),
            "TelCelular":   doc.get("TelCelular"),
            "IdWhatsApp":   doc.get("IdWhatsApp"),
            "IdTelegram":   doc.get("IdTelegram"),
            "ListaCorreos": doc.get("ListaCorreos"),
        }), 200
    except (InvalidId, Exception) as e:
        return jsonify({'error': str(e)}), 500


def get_datoscontactos(mongo):
    try:
        docs = mongo.db.datoscontacto.find()
        return Response(json_util.dumps(docs), mimetype="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def delete_datoscontacto(mongo, id):
    try:
        result = mongo.db.datoscontacto.delete_one({'EmpleadoId': ObjectId(id)})
        if result.deleted_count > 0:
            return jsonify({'message': f'Datos de contacto {id} eliminados'}), 200
        return jsonify({'message': 'No encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_datoscontacto(mongo, empleado_id, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos):
    try:
        TelFijo      = request.json.get('TelFijo', None)
        TelCelular   = request.json.get('TelCelular', None)
        IdWhatsApp   = request.json.get('IdWhatsApp', None)
        IdTelegram   = request.json.get('IdTelegram', None)
        ListaCorreos = request.json.get('ListaCorreos', None)

        mongo.db.datoscontacto.update_one(
            {'EmpleadoId': ObjectId(empleado_id)},
            {'$set': {
                'TelFijo':      TelFijo,
                'TelCelular':   TelCelular,
                'IdWhatsApp':   IdWhatsApp,
                'IdTelegram':   IdTelegram,
                'ListaCorreos': ListaCorreos,
            }}
        )
        return jsonify({'message': f'Datos de contacto actualizados para {empleado_id}'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def guardar_coordenadas_en_db(mongo, latitude, longitude):
    try:
        result = mongo.db.coordenadas.insert_one({'latitude': latitude, 'longitude': longitude})
        return {'_id': str(result.inserted_id), 'latitude': latitude, 'longitude': longitude}
    except Exception as e:
        raise Exception(f"Error al guardar coordenadas: {str(e)}")