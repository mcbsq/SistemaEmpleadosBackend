from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import json
import logging

from core.audit import registrar_auditoria, diff_documentos

logging.basicConfig(level=logging.DEBUG)


def json_handler(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _area_propia_empleado(mongo, identity):
    """
    depto_id del propio EMPLOYEE, resuelto vía su empleado_id.
    Se usa solo para el rol EMPLOYEE ("solo ve su propia área").
    """
    if not isinstance(identity, dict):
        return None
    empleado_id = identity.get('empleado_id')
    if not empleado_id:
        return None
    try:
        propio = mongo.db.empleados.find_one({'_id': ObjectId(empleado_id)})
    except (InvalidId, Exception):
        return None
    return propio.get('depto_id') if propio else None


def _equipo_directo_ids(mongo, identity):
    """
    IDs de empleados cuyo JefeInmediato_id (en rh) es el propio JEFE_AREA.
    Implementa el permiso "solo_equipo_directo": un JEFE_AREA solo ve a
    quienes le reportan directamente, no a todo el organigrama.
    """
    if not isinstance(identity, dict):
        return []
    own_empleado_id = identity.get('empleado_id')
    if not own_empleado_id:
        return []
    docs = mongo.db.rh.find({'JefeInmediato_id': str(own_empleado_id)}, {'empleado_id': 1})
    ids = []
    for d in docs:
        eid = d.get('empleado_id')
        try:
            ids.append(ObjectId(eid))
        except (InvalidId, TypeError):
            pass
    return ids


def _areas_admin(identity):
    """
    Lista de depto_id que un ADMIN tiene permitido administrar. Viene
    embebida en el JWT (campo areas_administradas), asignada por SUPER_ADMIN
    en POST/PUT /usuario — ver api/login/logic.py y api/usuario/logic.py.
    """
    if not isinstance(identity, dict):
        return []
    areas = identity.get('areas_administradas') or []
    return areas if isinstance(areas, list) else []


# --- CREATE ---
def create_empleado(mongo, identity=None):
    try:
        data = request.json
        if not data:
            return jsonify({'message': 'No se recibió un cuerpo JSON válido'}), 400

        nombre = data.get('Nombre')
        foto_input = data.get('Fotografia')
        lista_fotos = data.get('Fotografias', [])
        if foto_input and not lista_fotos:
            lista_fotos = [foto_input]

        if not nombre:
            return jsonify({'message': 'Faltan datos críticos: Nombre es requerido'}), 400

        depto_id = data.get('depto_id', 'Sin Asignar')

        role = identity.get('role') if isinstance(identity, dict) else None
        if role == 'ADMIN':
            areas = _areas_admin(identity)
            if not areas:
                return jsonify({'message': 'No tienes áreas asignadas para crear empleados'}), 403
            if depto_id not in areas:
                # Si no mandó una de sus áreas válidas, usa la primera permitida.
                depto_id = areas[0]

        emp = {
            'Nombre': nombre,
            'ApelPaterno': data.get('ApelPaterno', ''),
            'ApelMaterno': data.get('ApelMaterno', ''),
            'FecNacimiento': data.get('FecNacimiento', ''),
            'Fotografias': lista_fotos,
            'depto_id': depto_id,
            'Cargo': data.get('Cargo', 'Personal')
        }

        resultado = mongo.db.empleados.insert_one(emp)
        emp['_id'] = str(resultado.inserted_id)

        logging.debug(f"✅ Empleado insertado con ID: {emp['_id']}")
        return jsonify(emp), 201

    except Exception as e:
        logging.error(f"🔥 Error en create_empleado: {str(e)}")
        return jsonify({'message': 'Error interno del servidor', 'error': str(e)}), 500


# --- GET TODOS ---
def _empleado_ids_super_admin(mongo):
    """
    IDs de empleado vinculados a una cuenta SUPER_ADMIN. Un SUPER_ADMIN es una
    cuenta administrativa de la empresa (o de Cibercom), no una persona en la
    plantilla — no debe aparecer en el Organigrama ni ser dado de alta en la
    tabla de RH. create_usuario/update_usuario ya evitan que se les asigne un
    empleado_id de entrada; este filtro es la segunda barrera (defensa en
    profundidad) para datos existentes que hayan quedado vinculados antes de
    esa regla, o por cualquier otra vía.
    """
    # empleado_id vive inconsistentemente en Mongo: unas veces ObjectId, otras
    # string (dato legacy, ver diccionario de datos) — normalizar a ObjectId
    # aquí, o el $nin de abajo nunca hace match contra empleados._id real.
    ids = []
    for u in mongo.db.usuario.find({"role": "SUPER_ADMIN"}):
        raw = u.get("empleado_id")
        if not raw:
            continue
        try:
            ids.append(raw if isinstance(raw, ObjectId) else ObjectId(raw))
        except (InvalidId, TypeError):
            ids.append(raw)  # dejar tal cual si de plano no es un ObjectId válido
    return ids


def get_empleados(mongo, identity=None):
    try:
        query = {"estado": {"$ne": "pendiente"}}

        role = identity.get('role') if isinstance(identity, dict) else None
        if role == 'ADMIN':
            areas = _areas_admin(identity)
            query["depto_id"] = {"$in": areas} if areas else "__sin_area_asignada__"
        elif role == 'EMPLOYEE':
            area_propia = _area_propia_empleado(mongo, identity)
            query["depto_id"] = area_propia if area_propia else "__sin_area_asignada__"
        elif role == 'JEFE_AREA':
            # "solo_equipo_directo": nunca ve la nómina completa, solo a
            # quienes le reportan (rh.JefeInmediato_id == su empleado_id).
            equipo = _equipo_directo_ids(mongo, identity)
            query["_id"] = {"$in": equipo} if equipo else {"$in": []}
        # CONTADOR, PROJECT_MANAGER y MEDICO ven la nómina completa: la
        # analítica financiera, de proyectos y clínica opera a nivel empresa.

        excluir_ids = _empleado_ids_super_admin(mongo)
        if excluir_ids:
            id_actual = query.get("_id")
            if isinstance(id_actual, dict) and "$in" in id_actual:
                # JEFE_AREA: intersectar en vez de pisar el filtro existente.
                id_actual["$in"] = [i for i in id_actual["$in"] if i not in excluir_ids]
            else:
                query["_id"] = {"$nin": excluir_ids}

        empleados = list(mongo.db.empleados.find(query))
        formatted = []
        for e in empleados:
            formatted.append({
                '_id': str(e["_id"]),
                'Nombre': e.get("Nombre"),
                'ApelPaterno': e.get("ApelPaterno"),
                'ApelMaterno': e.get("ApelMaterno"),
                'Cargo': e.get("Cargo"),
                'depto_id': e.get("depto_id"),
                'FecNacimiento': e.get("FecNacimiento"),
                'Fotografias': e.get("Fotografias", [])
            })
        return Response(json.dumps(formatted), mimetype="application/json")
    except Exception as e:
        logging.error(f"🔥 Error en get_empleados: {str(e)}")
        return jsonify({'error': str(e)}), 500


# --- GET POR ID ---
def get_empleado(id, mongo, identity=None):
    try:
        empleado = mongo.db.empleados.find_one({'_id': ObjectId(id)})
        if not empleado:
            return jsonify({'message': 'Empleado no encontrado'}), 404

        role = identity.get('role') if isinstance(identity, dict) else None
        if role == 'ADMIN':
            areas = _areas_admin(identity)
            if empleado.get('depto_id') not in areas:
                return jsonify({'error': 'Acceso no autorizado'}), 403
        # EMPLOYEE ya viene limitado a su propio id por require_self_or_roles en routes.py.

        return Response(json_util.dumps(empleado), mimetype="application/json")
    except Exception as e:
        return jsonify({'message': 'ID inválido', 'error': str(e)}), 400


# Colecciones que cuelgan de un empleado y su campo de vínculo. Antes el
# DELETE no las tocaba: cada empleado borrado dejaba RH/dirección/contactos/
# educación/expediente huérfanos para siempre en Mongo (encontrado auditando
# los dashboards de CONTADOR/MEDICO, que sí listan esas colecciones completas).
_COLECCIONES_HIJAS = {
    'rh':                'empleado_id',   # ObjectId
    'direccion':         'empleado_id',   # string
    'datoscontacto':     'EmpleadoId',    # ObjectId
    'personascontacto':  'empleado_id',   # string
    'educacion':         'empleado_id',   # ObjectId
    'expedienteclinico': 'empleado_id',   # string
    'redsocial':         'empleado_id',   # string
}


# --- DELETE ---
def delete_empleado(id, mongo, identity=None):
    # Sin cambios en la restricción de rol: ya limitado a SUPER_ADMIN en la ruta.
    try:
        eid = ObjectId(id)
        empleado_borrado = mongo.db.empleados.find_one({'_id': eid})
        result = mongo.db.empleados.delete_one({'_id': eid})
        if result.deleted_count == 0:
            return jsonify({'message': 'No se encontró el empleado para eliminar'}), 404

        borrados = 0
        for coleccion, campo in _COLECCIONES_HIJAS.items():
            r1 = mongo.db[coleccion].delete_many({campo: eid})
            r2 = mongo.db[coleccion].delete_many({campo: id})
            borrados += r1.deleted_count + r2.deleted_count

        if isinstance(identity, dict):
            registrar_auditoria(
                mongo, identity.get('user'), identity.get('role'),
                'delete', 'empleados', id,
                detalle=f"Nombre: {empleado_borrado.get('Nombre','')} {empleado_borrado.get('ApelPaterno','')}" if empleado_borrado else None,
            )

        return jsonify({
            'message': f'Empleado {id} eliminado exitosamente',
            'documentos_relacionados_eliminados': borrados,
        }), 200
    except Exception as e:
        return jsonify({'message': 'Error al procesar el ID', 'error': str(e)}), 400


# --- UPDATE ---
def update_empleado(id, mongo, identity=None):
    try:
        data = request.json
        if not data:
            return jsonify({'message': 'Datos no proporcionados'}), 400

        role = identity.get('role') if isinstance(identity, dict) else None
        areas = _areas_admin(identity) if role == 'ADMIN' else []

        if role == 'ADMIN':
            empleado_actual = mongo.db.empleados.find_one({'_id': ObjectId(id)})
            if not empleado_actual:
                return jsonify({'message': 'Empleado no encontrado'}), 404
            if empleado_actual.get('depto_id') not in areas:
                return jsonify({'error': 'Acceso no autorizado'}), 403

        # Solo se incluyen los campos que el caller realmente mandó — un PUT
        # parcial (ej. solo {"Cargo": "..."}) no debe borrar el resto de los
        # campos del empleado con null.
        up = {
            campo: data[campo]
            for campo in ('Nombre', 'ApelPaterno', 'ApelMaterno', 'Cargo', 'FecNacimiento', 'Fotografias')
            if campo in data
        }

        if 'depto_id' in data:
            if role == 'ADMIN':
                # Un ADMIN solo puede mover al empleado ENTRE sus propias áreas.
                if data['depto_id'] in areas:
                    up['depto_id'] = data['depto_id']
                # si pide un área fuera de las suyas, se ignora ese campo
                # (el resto de la actualización sigue adelante).
            else:
                up['depto_id'] = data['depto_id']

        antes = mongo.db.empleados.find_one({'_id': ObjectId(id)}) or {}
        mongo.db.empleados.update_one({'_id': ObjectId(id)}, {'$set': up})

        cambios = diff_documentos(antes, {**antes, **up})
        if cambios:
            registrar_auditoria(mongo, identity.get('user') if isinstance(identity, dict) else None,
                                 role, 'update', 'empleados', id, cambios=cambios)

        return jsonify({'message': 'Actualizado exitosamente'}), 200
    except Exception as e:
        return jsonify({'message': 'Error al actualizar', 'error': str(e)}), 400


def get_empleados_sin_pendientes(mongo):
    try:
        empleados = list(mongo.db.empleados.find({"estado": {"$ne": "pendiente"}}))
        return empleados
    except Exception as e:
        logging.error(f"Error en get_empleados_sin_pendientes: {e}")
        raise


def aprobar_empleado(mongo, empleado_id):
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