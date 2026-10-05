# api/perfil/routes.py
# ─────────────────────────────────────────────────────────────────────────────
# Puerta de entrada del perfil para el frontend (web y mobile):
#   GET /perfil/<id>/acceso  → qué secciones puede ver/editar quien pregunta
#                              (la matriz de core/visibilidad_perfil.py).
#   GET /perfil/<id>/publico → la "tarjeta" que cualquier compañero de la
#                              misma empresa puede ver: nombre, foto, puesto,
#                              área, jefe y correo de trabajo. Nada personal.
# Antes un EMPLOYEE no podía abrir el perfil de un compañero (GET /empleados/<id>
# es solo propio/RH) y el frontend se quedaba en "Cargando perfil…".
# ─────────────────────────────────────────────────────────────────────────────
from bson.objectid import ObjectId
from bson.errors import InvalidId
import re

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt

from core.audit import registrar_auditoria
from core.visibilidad_perfil import acceso_perfil, _str_id, ROLES_RH

# Foto de perfil: el frontend la recorta y comprime (512 px, JPEG/WebP) antes
# de mandarla; este límite solo frena que alguien suba un archivo enorme
# saltándose la interfaz (~1.5 MB de imagen en base64).
_FOTO_MAX_CHARS = 2_000_000
_FOTO_RE = re.compile(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$")


def _foto(emp):
    fotos = emp.get("Fotografias") or []
    return fotos[0] if fotos else (emp.get("Fotografia") or None)


def setup_perfil_routes(app, mongo):

    @app.route('/perfil/<empleado_id>/acceso', methods=['GET'])
    @jwt_required()
    def perfil_acceso_route(empleado_id):
        return jsonify(acceso_perfil(mongo, get_jwt(), empleado_id)), 200

    @app.route('/perfil/<empleado_id>/publico', methods=['GET'])
    @jwt_required()
    def perfil_publico_route(empleado_id):
        try:
            eid = ObjectId(empleado_id)
        except (InvalidId, TypeError):
            return jsonify({'error': 'ID inválido'}), 400

        emp = mongo.db.empleados.find_one({'_id': eid})
        if not emp:
            return jsonify({'error': 'Empleado no encontrado'}), 404

        rh = mongo.db.rh.find_one({'empleado_id': eid}, {
            'Puesto': 1, 'Departamento': 1, 'JefeInmediato': 1, 'JefeInmediato_id': 1,
        }) or {}
        cuenta = mongo.db.usuario.find_one({'empleado_id': {'$in': [eid, str(eid)]}}, {'email': 1}) or {}

        return jsonify({
            '_id':              str(eid),
            'Nombre':           emp.get('Nombre', ''),
            'ApelPaterno':      emp.get('ApelPaterno', ''),
            'ApelMaterno':      emp.get('ApelMaterno', ''),
            'Fotografias':      [f for f in [_foto(emp)] if f],
            'Puesto':           rh.get('Puesto', ''),
            # El área vive en dos lugares por historia (ficha laboral y
            # empleados.depto_id); si la ficha no la tiene, se usa la otra.
            'Departamento':     rh.get('Departamento') or (emp.get('depto_id') if str(emp.get('depto_id') or '').strip().lower() != 'sin asignar' else '') or '',
            'JefeInmediato':    rh.get('JefeInmediato', ''),
            'JefeInmediato_id': _str_id(rh.get('JefeInmediato_id')),
            # El correo de la cuenta de acceso es el de trabajo; los correos
            # de "Datos de contacto" son personales y no salen aquí.
            'CorreoLaboral':    cuenta.get('email') or '',
            # Personalización del propio empleado (Ajustes de perfil).
            'NombrePreferido':  emp.get('NombrePreferido', ''),
            'Titular':          emp.get('Titular', ''),
            'estado':           emp.get('estado', 'activo'),
            # Los datos de la salida (motivo incluido) solo los ve RH.
            'baja':             emp.get('baja') if emp.get('estado') == 'baja' and get_jwt().get('role') in ROLES_RH else None,
        }), 200

    # Ajustes de perfil (estilo red social): lo que el propio empleado decide
    # de cómo se presenta — foto, nombre con el que lo conocen y una frase
    # corta. El nombre LEGAL (Nombre/Apellidos) sigue siendo de RH: aparece
    # en contratos y nómina, así que no se toca aquí.
    @app.route('/perfil/<empleado_id>/ajustes', methods=['PATCH'])
    @jwt_required()
    def perfil_ajustes_route(empleado_id):
        identity = get_jwt()
        es_propio = str(identity.get('empleado_id') or '') == str(empleado_id)
        if not es_propio and identity.get('role') not in ROLES_RH:
            return jsonify({'error': 'Solo puedes cambiar tu propio perfil'}), 403
        try:
            eid = ObjectId(empleado_id)
        except (InvalidId, TypeError):
            return jsonify({'error': 'ID inválido'}), 400

        data = request.get_json(silent=True) or {}
        cambios, errores = {}, {}

        if 'NombrePreferido' in data:
            nombre = re.sub(r'\s+', ' ', str(data.get('NombrePreferido') or '')).strip()
            if len(nombre) > 60:
                errores['NombrePreferido'] = 'Máximo 60 caracteres.'
            else:
                cambios['NombrePreferido'] = nombre
        if 'Titular' in data:
            titular = re.sub(r'\s+', ' ', str(data.get('Titular') or '')).strip()
            if len(titular) > 120:
                errores['Titular'] = 'Máximo 120 caracteres.'
            else:
                cambios['Titular'] = titular
        if 'Fotografia' in data:
            foto = data.get('Fotografia')
            if foto in (None, ''):
                cambios['Fotografias'] = []
            elif not isinstance(foto, str) or len(foto) > _FOTO_MAX_CHARS or not _FOTO_RE.match(foto):
                errores['Fotografia'] = 'La foto debe ser una imagen JPG, PNG o WebP de menos de 1.5 MB.'
            else:
                cambios['Fotografias'] = [foto]

        if errores:
            return jsonify({'error': 'Revisa los datos marcados.', 'campos': errores}), 400
        if not cambios:
            return jsonify({'message': 'Sin cambios'}), 200

        res = mongo.db.empleados.update_one({'_id': eid}, {'$set': cambios})
        if res.matched_count == 0:
            return jsonify({'error': 'Empleado no encontrado'}), 404
        registrar_auditoria(mongo, identity.get('user'), identity.get('role'), 'update',
                            'perfil_ajustes', str(eid),
                            detalle=', '.join(sorted(k for k in cambios)))
        return jsonify({'message': 'Perfil actualizado'}), 200
