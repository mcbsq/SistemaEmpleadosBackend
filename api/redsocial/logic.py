# api/redsocial/logic.py
from flask import jsonify, Response
from bson.objectid import ObjectId
from bson import json_util
import logging

logger = logging.getLogger(__name__)


def json_handler(obj):
    """Manejador para la serialización JSON que maneja ObjectId."""
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def create_or_update_redsocial(mongo, empleado_id, redes_sociales):
    try:
        if not empleado_id:
            return jsonify({'error': 'Datos insuficientes para crear o actualizar redes sociales'}), 400

        eid = ObjectId(empleado_id)
        existing_data = mongo.db.redsocial.find_one({'empleado_id': eid})

        if existing_data:
            mongo.db.redsocial.update_one(
                {'empleado_id': eid},
                {'$set': {'RedesSociales': redes_sociales}}
            )
        else:
            result = mongo.db.redsocial.insert_one({
                'empleado_id': eid,
                'RedesSociales': redes_sociales
            })
            logger.debug(f"redsocial insertado: {result.inserted_id}")

        return jsonify({
            'empleado_id': empleado_id,
            'message': 'Datos de redes sociales creados o actualizados exitosamente'
        }), 201

    except Exception as e:
        logger.error(f"Error en create_or_update_redsocial: {e}")
        return jsonify({'message': 'Error al procesar la solicitud'}), 500


def get_redessociales_empleado(mongo, empleado_id):
    try:
        empleado_id_obj = ObjectId(empleado_id)
        redes_sociales = mongo.db.redsocial.find({'empleado_id': empleado_id_obj})
        result = list(redes_sociales)

        formatted_result = []
        for red_social in result:
            redes_sociales_list = red_social.get('RedesSociales', [])
            formatted_result.append({
                '_id': str(red_social['_id']),
                "empleado_id": str(red_social['empleado_id']),
                'RedesSociales': [
                    {
                        'redSocialSeleccionada': red.get('redSocialSeleccionada', ''),
                        'URLRedSocial': red.get('URLRedSocial', ''),
                        'NombreRedSocial': red.get('NombreRedSocial', '')
                    } for red in redes_sociales_list
                ]
            })

        return jsonify(formatted_result)
    except Exception as e:
        logger.error(f"Error en get_redessociales_empleado: {e}")
        return jsonify({'message': 'Error en la consulta de redes sociales'}), 500


def obtener_lista_de_empleados(mongo):
    return list(mongo.db.empleados.find())


def get_redsocial(mongo):
    redsocial_list = list(mongo.db.redsocial.find())
    empleados = obtener_lista_de_empleados(mongo)

    for redsocial in redsocial_list:
        empleado_id = redsocial.get("empleado_id")
        empleado_nombre = ""
        for empleado in empleados:
            if str(empleado.get("_id")) == str(empleado_id):
                empleado_nombre = f"{empleado.get('Nombre')} {empleado.get('ApelPaterno')} {empleado.get('ApelMaterno')}"
                break
        redsocial["NombreCompleto"] = empleado_nombre

    return Response(json_util.dumps(redsocial_list), mimetype="application/json")


def delete_redsocial(mongo, empleado_id):
    try:
        object_id = ObjectId(empleado_id)
        result = mongo.db.redsocial.delete_one({'empleado_id': object_id})

        if result.deleted_count > 0:
            return jsonify({'message': f'Red Social {empleado_id} eliminada exitosamente'}), 200
        return jsonify({'message': f'No se encontró Red Social para el id {empleado_id}'}), 404

    except Exception as e:
        logger.error(f"Error en delete_redsocial: {e}")
        return jsonify({'error': str(e)}), 500


def update_redessociales_empleado(mongo, empleado_id, redes_sociales_nuevas):
    try:
        empleado_id_obj = ObjectId(empleado_id)
        existing_data = mongo.db.redsocial.find_one({'empleado_id': empleado_id_obj})

        if existing_data:
            mongo.db.redsocial.update_one(
                {'empleado_id': empleado_id_obj},
                {'$set': {'RedesSociales': redes_sociales_nuevas}}
            )
            return jsonify({
                'empleado_id': str(empleado_id_obj),
                'message': 'Datos de redes sociales actualizados exitosamente'
            }), 200
        else:
            result = mongo.db.redsocial.insert_one({
                'empleado_id': empleado_id_obj,
                'RedesSociales': redes_sociales_nuevas
            })
            logger.debug(f"redsocial insertado: {result.inserted_id}")
            return jsonify({
                'empleado_id': str(empleado_id_obj),
                'message': 'Datos de redes sociales creados exitosamente'
            }), 201

    except Exception as e:
        logger.error(f"Error en update_redessociales_empleado: {e}")
        return jsonify({'message': 'Error al actualizar redes sociales del empleado'}), 500