import re
# api/datoscontacto/logic.py
from flask import jsonify, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)


def _digitos(tel):
    return re.sub(r"\D", "", str(tel or ""))


def validar_telefonos(TelFijo, TelCelular, IdWhatsApp):
    """Errores por campo ({} si todo bien). WhatsApp puede ser el mismo
    número que el celular (es lo normal); celular y fijo no."""
    errores = {}
    for campo, valor in (("TelCelular", TelCelular), ("TelFijo", TelFijo), ("IdWhatsApp", IdWhatsApp)):
        d = _digitos(valor)
        if d and not 10 <= len(d) <= 15:
            errores[campo] = "Escribe el número a 10 dígitos (con lada)."
        elif d and len(set(d)) == 1:
            errores[campo] = "Ese número no parece real."
    cel, fijo = _digitos(TelCelular)[-10:], _digitos(TelFijo)[-10:]
    if cel and fijo and cel == fijo and "TelFijo" not in errores:
        errores["TelFijo"] = "El teléfono fijo no puede ser el mismo que el celular; déjalo vacío si no tiene."
    return errores


_CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validar_correos(lista):
    """Correos del empleado: formato válido y sin repetir (mayúsculas no cuentan)."""
    vistos = set()
    for item in lista or []:
        email = str((item.get("email") if isinstance(item, dict) else item) or "").strip().lower()
        if not email:
            continue
        if not _CORREO_RE.match(email):
            return {"ListaCorreos": f'"{email}" no es un correo válido.'}
        if email in vistos:
            return {"ListaCorreos": f'El correo {email} está repetido.'}
        vistos.add(email)
    return {}


def create_datoscontacto(mongo, TelFijo, TelCelular, IdWhatsApp, IdTelegram, ListaCorreos, empleado_id):
    errores = validar_telefonos(TelFijo, TelCelular, IdWhatsApp) or validar_correos(ListaCorreos)
    if errores:
        return jsonify({'error': 'Revisa los datos de contacto.', 'campos': errores}), 400
    try:
        result = mongo.db.datoscontacto.insert_one({
            'EmpleadoId':   ObjectId(empleado_id),
            'TelFijo':      TelFijo,
            'TelCelular':   TelCelular,
            'IdWhatsApp':   IdWhatsApp,
            'IdTelegram':   IdTelegram,
            'ListaCorreos': ListaCorreos,
        })

        return jsonify({
            '_id':          str(result.inserted_id),
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
    errores = validar_telefonos(TelFijo, TelCelular, IdWhatsApp) or validar_correos(ListaCorreos)
    if errores:
        return jsonify({'error': 'Revisa los datos de contacto.', 'campos': errores}), 400
    try:
        # FIX: sin upsert=True, un empleado que nunca tuvo datoscontacto
        # creado (nadie llamó create_datoscontacto para él) hacía que este
        # update_one no encontrara ningún documento que tocar — respondía
        # 200 igual, pero no guardaba nada. Auto-guardado desde el perfil
        # (Perfil.js) llama a este mismo endpoint sin pasar antes por un
        # alta explícita, así que esto se disparaba todo el tiempo.
        eid = ObjectId(empleado_id)
        mongo.db.datoscontacto.update_one(
            {'EmpleadoId': eid},
            {'$set': {
                'EmpleadoId':   eid,
                'TelFijo':      TelFijo,
                'TelCelular':   TelCelular,
                'IdWhatsApp':   IdWhatsApp,
                'IdTelegram':   IdTelegram,
                'ListaCorreos': ListaCorreos,
            }},
            upsert=True,
        )
        return jsonify({'message': f'Datos de contacto actualizados para {empleado_id}'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# guardar_coordenadas_en_db se eliminó — confirmado en desuso (código
# huérfano de un enfoque anterior; MapaDomicilio.jsx guarda lat/lng
# directo en el documento de `direccion`). Si en algún momento revives esta
# idea, hazlo ligado a empleado_id desde el inicio.