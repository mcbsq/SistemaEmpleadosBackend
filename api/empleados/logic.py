from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
import json
import logging

logging.basicConfig(level=logging.DEBUG)

def json_handler(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

# --- CREATE ---
def create_empleado(mongo):
    try:
        data = request.json
        if not data:
            return jsonify({'message': 'No se recibió un cuerpo JSON válido'}), 400

        nombre     = data.get('Nombre')
        foto_input = data.get('Fotografia')
        lista_fotos = data.get('Fotografias', [])

        if foto_input and not lista_fotos:
            lista_fotos = [foto_input]

        if nombre:
            emp = {
                'Nombre':       nombre,
                'ApelPaterno':  data.get('ApelPaterno', ''),
                'ApelMaterno':  data.get('ApelMaterno', ''),
                'FecNacimiento': data.get('FecNacimiento', ''),
                'Fotografias':  lista_fotos,
                'depto_id':     data.get('depto_id', 'Sin Asignar'),
                'Cargo':        data.get('Cargo', 'Personal'),
                'estado':       'activo',   # ← nuevo: todos arrancan activos
            }
            resultado = mongo.db.empleados.insert_one(emp)
            emp['_id'] = str(resultado.inserted_id)
            logging.debug(f"✅ Empleado insertado con ID: {emp['_id']}")
            return jsonify(emp), 201

        return jsonify({'message': 'Faltan datos críticos: Nombre es requerido'}), 400

    except Exception as e:
        logging.error(f"🔥 Error en create_empleado: {str(e)}")
        return jsonify({'message': 'Error interno del servidor', 'error': str(e)}), 500


# --- GET TODOS ---
# CAMBIOS:
#   · Expone el campo `estado` (necesario para el toggle activo/inactivo del frontend)
#   · Expone `FecIngreso` si existe (para la columna Ingreso)
#   · Filtra pendientes igual que antes
def get_empleados(mongo):
    try:
        empleados = list(mongo.db.empleados.find(
            {"estado": {"$ne": "pendiente"}}
        ))
        formatted = []
        for e in empleados:
            formatted.append({
                '_id':          str(e["_id"]),
                'Nombre':       e.get("Nombre"),
                'ApelPaterno':  e.get("ApelPaterno"),
                'ApelMaterno':  e.get("ApelMaterno"),
                'Cargo':        e.get("Cargo"),
                'depto_id':     e.get("depto_id"),
                'FecNacimiento': e.get("FecNacimiento"),
                'FecIngreso':   e.get("FecIngreso", ""),      # ← nuevo
                'Fotografias':  e.get("Fotografias", []),
                'estado':       e.get("estado", "activo"),    # ← nuevo (antes no se exponía)
            })
        return Response(json.dumps(formatted), mimetype="application/json")
    except Exception as e:
        logging.error(f"🔥 Error en get_empleados: {str(e)}")
        return jsonify({'error': str(e)}), 500


# --- GET POR ID ---
def get_empleado(id, mongo):
    try:
        empleado = mongo.db.empleados.find_one({'_id': ObjectId(id)})
        if empleado:
            return Response(json_util.dumps(empleado), mimetype="application/json")
        return jsonify({'message': 'Empleado no encontrado'}), 404
    except Exception as e:
        return jsonify({'message': 'ID inválido', 'error': str(e)}), 400


# --- DELETE ---
def delete_empleado(id, mongo):
    try:
        result = mongo.db.empleados.delete_one({'_id': ObjectId(id)})
        if result.deleted_count > 0:
            return jsonify({'message': f'Empleado {id} eliminado exitosamente'}), 200
        return jsonify({'message': 'No se encontró el empleado para eliminar'}), 404
    except Exception as e:
        return jsonify({'message': 'Error al procesar el ID', 'error': str(e)}), 400


# --- UPDATE ---
def update_empleado(id, mongo):
    try:
        data = request.json
        if not data:
            return jsonify({'message': 'Datos no proporcionados'}), 400

        up = {
            'Nombre':        data.get('Nombre'),
            'ApelPaterno':   data.get('ApelPaterno'),
            'ApelMaterno':   data.get('ApelMaterno'),
            'Cargo':         data.get('Cargo'),
            'depto_id':      data.get('depto_id'),
            'FecNacimiento': data.get('FecNacimiento'),
            'FecIngreso':    data.get('FecIngreso', ''),   # ← nuevo
            'Fotografias':   data.get('Fotografias', []),
            # No sobreescribir `estado` desde update general — usar /aprobar o /desactivar
        }
        mongo.db.empleados.update_one({'_id': ObjectId(id)}, {'$set': up})
        return jsonify({'message': 'Actualizado exitosamente'}), 200
    except Exception as e:
        return jsonify({'message': 'Error al actualizar', 'error': str(e)}), 400


# --- APROBAR (pendiente → activo) ---
def aprobar_empleado(mongo, empleado_id):
    from bson.errors import InvalidId
    try:
        result = mongo.db.empleados.update_one(
            {"_id": ObjectId(empleado_id), "estado": "pendiente"},
            {"$set": {"estado": "activo"}}
        )
        if result.modified_count == 0:
            return jsonify({"error": "Empleado no encontrado o ya estaba activo"}), 404
        return jsonify({"message": f"Empleado {empleado_id} aprobado"}), 200
    except (InvalidId, Exception) as e:
        return jsonify({"error": str(e)}), 400


# --- DESACTIVAR (activo → inactivo) — NUEVO ---
# Endpoint sugerido: PATCH /empleados/<id>/desactivar  (solo ADMIN/SUPER_ADMIN)
def desactivar_empleado(mongo, empleado_id):
    from bson.errors import InvalidId
    try:
        result = mongo.db.empleados.update_one(
            {"_id": ObjectId(empleado_id)},
            {"$set": {"estado": "inactivo"}}
        )
        if result.modified_count == 0:
            return jsonify({"error": "Empleado no encontrado"}), 404
        return jsonify({"message": f"Empleado {empleado_id} desactivado"}), 200
    except (InvalidId, Exception) as e:
        return jsonify({"error": str(e)}), 400


# --- REACTIVAR (inactivo → activo) — NUEVO ---
# Endpoint sugerido: PATCH /empleados/<id>/reactivar  (solo ADMIN/SUPER_ADMIN)
def reactivar_empleado(mongo, empleado_id):
    from bson.errors import InvalidId
    try:
        result = mongo.db.empleados.update_one(
            {"_id": ObjectId(empleado_id), "estado": "inactivo"},
            {"$set": {"estado": "activo"}}
        )
        if result.modified_count == 0:
            return jsonify({"error": "Empleado no encontrado o ya estaba activo"}), 404
        return jsonify({"message": f"Empleado {empleado_id} reactivado"}), 200
    except (InvalidId, Exception) as e:
        return jsonify({"error": str(e)}), 400


# --- Helper sin pendientes (uso interno) ---
def get_empleados_sin_pendientes(mongo):
    try:
        return list(mongo.db.empleados.find({"estado": {"$ne": "pendiente"}}))
    except Exception as e:
        logging.error(f"Error en get_empleados_sin_pendientes: {e}")
        raise