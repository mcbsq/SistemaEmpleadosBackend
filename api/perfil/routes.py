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
from core.permissions import require_roles_or_permission
from core.visibilidad_perfil import acceso_perfil, _str_id, ROLES_RH, tarjeta_directorio

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
            'Extension': 1, 'TelefonoOficina': 1, 'UbicacionOficina': 1,
        }) or {}
        cuenta = mongo.db.usuario.find_one({'empleado_id': {'$in': [eid, str(eid)]}}, {'email': 1}) or {}
        contacto = mongo.db.datoscontacto.find_one({'EmpleadoId': eid}, {'TelCelular': 1, 'ListaCorreos': 1}) or {}

        # Qué ve de esta persona quien pregunta lo decide su rol (permisos de
        # Directorio en Gestión de roles) — ver core/visibilidad_perfil.py.
        tarjeta = tarjeta_directorio(mongo, get_jwt(), emp, rh, cuenta, contacto)
        tarjeta.update({
            # El estado de empleo (activo/baja) lo usa la página de perfil;
            # "estado" de disponibilidad puede venir de la tarjeta.
            'estado':           tarjeta.get('estado') or emp.get('estado', 'activo'),
            # Los datos de la salida (motivo incluido) solo los ve RH.
            'baja':             emp.get('baja') if emp.get('estado') == 'baja' and get_jwt().get('role') in ROLES_RH else None,
        })
        return jsonify(tarjeta), 200

    # Directorio de la empresa: una tarjeta por persona activa, con lo que
    # el rol de quien consulta tiene permitido ver.
    @app.route('/directorio', methods=['GET'])
    @jwt_required()
    def directorio_route():
        identity = get_jwt()
        empleados = list(mongo.db.empleados.find({'estado': {'$ne': 'baja'}}, {
            'Nombre': 1, 'ApelPaterno': 1, 'ApelMaterno': 1, 'NombrePreferido': 1, 'Titular': 1,
            'Fotografias': {'$slice': 1}, 'Fotografia': 1, 'FecNacimiento': 1, 'estado': 1, 'depto_id': 1,
        }))
        ids = [e['_id'] for e in empleados]
        rhs = {str(r.get('empleado_id')): r for r in mongo.db.rh.find({'empleado_id': {'$in': ids}}, {
            'empleado_id': 1, 'Puesto': 1, 'Departamento': 1, 'JefeInmediato': 1, 'JefeInmediato_id': 1,
            'Extension': 1, 'TelefonoOficina': 1, 'UbicacionOficina': 1,
        })}
        cuentas = {str(c.get('empleado_id')): c for c in mongo.db.usuario.find(
            {'empleado_id': {'$in': ids + [str(i) for i in ids]}}, {'empleado_id': 1, 'email': 1})}
        contactos = {str(c.get('EmpleadoId')): c for c in mongo.db.datoscontacto.find(
            {'EmpleadoId': {'$in': ids}}, {'EmpleadoId': 1, 'TelCelular': 1, 'ListaCorreos': 1})}
        q = (request.args.get('q') or '').strip().lower()
        tarjetas = []
        for e in empleados:
            k = str(e['_id'])
            t = tarjeta_directorio(mongo, identity, e, rhs.get(k), cuentas.get(k), contactos.get(k))
            texto = ' '.join(str(t.get(c, '')) for c in ('Nombre', 'ApelPaterno', 'NombrePreferido', 'Puesto', 'Departamento', 'Extension')).lower()
            if not q or q in texto:
                tarjetas.append(t)
        tarjetas.sort(key=lambda t: (t.get('Nombre', '') + ' ' + t.get('ApelPaterno', '')).lower())
        return jsonify(tarjetas), 200

    # Organigrama por jerarquía: una entrada por persona activa con su jefe
    # inmediato (el de su ficha laboral). El frontend arma el árbol; quien no
    # tiene jefe ni equipo queda aparte como "sin jefe asignado".
    @app.route('/organigrama', methods=['GET'])
    @require_roles_or_permission(mongo, 'ver_organigrama', 'EMPLOYEE', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR',
                                 'PROJECT_MANAGER', 'JEFE_AREA', 'MEDICO')
    def organigrama_route():
        empleados = list(mongo.db.empleados.find({'estado': {'$nin': ['pendiente', 'baja']}}, {
            'Nombre': 1, 'ApelPaterno': 1, 'NombrePreferido': 1, 'Fotografias': {'$slice': 1},
            'Fotografia': 1, 'depto_id': 1}))
        activos = {str(e['_id']) for e in empleados}
        rhs = {str(r.get('empleado_id')): r for r in mongo.db.rh.find(
            {'empleado_id': {'$in': [e['_id'] for e in empleados]}},
            {'empleado_id': 1, 'Puesto': 1, 'Departamento': 1, 'JefeInmediato_id': 1})}
        nodos = []
        for e in empleados:
            k = str(e['_id'])
            rh = rhs.get(k, {})
            jefe = _str_id(rh.get('JefeInmediato_id'))
            fotos = e.get('Fotografias') or []
            depto = rh.get('Departamento') or e.get('depto_id') or ''
            nodos.append({
                '_id':          k,
                'Nombre':       e.get('NombrePreferido') or e.get('Nombre', ''),
                'ApelPaterno':  e.get('ApelPaterno', ''),
                'Foto':         fotos[0] if fotos else e.get('Fotografia'),
                'Puesto':       rh.get('Puesto', ''),
                'Departamento': '' if str(depto).strip().lower() == 'sin asignar' else depto,
                # Un jefe dado de baja o inexistente no cuelga a nadie del árbol.
                'JefeInmediato_id': jefe if jefe in activos and jefe != k else '',
            })
        return jsonify(nodos), 200

    # Mini organigrama del perfil: la persona, su cadena de mando (hasta
    # `niveles` jefes hacia arriba) y quiénes le reportan directamente.
    @app.route('/perfil/<empleado_id>/cadena-mando', methods=['GET'])
    @jwt_required()
    def cadena_mando_route(empleado_id):
        try:
            eid = ObjectId(empleado_id)
        except (InvalidId, TypeError):
            return jsonify({'error': 'ID inválido'}), 400
        niveles = max(1, min(int(request.args.get('niveles', 3) or 3), 6))

        def nodo(oid):
            emp = mongo.db.empleados.find_one({'_id': oid}, {
                'Nombre': 1, 'ApelPaterno': 1, 'NombrePreferido': 1, 'Fotografias': {'$slice': 1}, 'Fotografia': 1, 'estado': 1})
            if not emp:
                return None, {}
            rh = mongo.db.rh.find_one({'empleado_id': oid}, {'Puesto': 1, 'Departamento': 1, 'JefeInmediato_id': 1, 'JefeInmediato': 1}) or {}
            fotos = emp.get('Fotografias') or []
            return {
                '_id':          str(oid),
                'Nombre':       emp.get('NombrePreferido') or emp.get('Nombre', ''),
                'ApelPaterno':  emp.get('ApelPaterno', ''),
                'Foto':         fotos[0] if fotos else emp.get('Fotografia'),
                'Puesto':       rh.get('Puesto', ''),
                'Departamento': rh.get('Departamento', ''),
                'baja':         emp.get('estado') == 'baja',
            }, rh

        actual, rh = nodo(eid)
        if not actual:
            return jsonify({'error': 'Empleado no encontrado'}), 404

        superiores, vistos = [], {str(eid)}
        jefe_id, jefe_nombre = _str_id(rh.get('JefeInmediato_id')), rh.get('JefeInmediato', '')
        while len(superiores) < niveles and (jefe_id or jefe_nombre):
            if not jefe_id or jefe_id in vistos:
                # Jefe capturado solo con nombre (sin ficha enlazada) o ciclo.
                if jefe_nombre and jefe_id not in vistos:
                    superiores.append({'_id': None, 'Nombre': jefe_nombre, 'ApelPaterno': '', 'Puesto': '', 'Departamento': ''})
                break
            try:
                n, rh_j = nodo(ObjectId(jefe_id))
            except (InvalidId, TypeError):
                n, rh_j = None, {}
            if not n:
                break
            vistos.add(jefe_id)
            superiores.append(n)
            jefe_id, jefe_nombre = _str_id(rh_j.get('JefeInmediato_id')), rh_j.get('JefeInmediato', '')
        hay_mas = bool(jefe_id and jefe_id not in vistos) if len(superiores) == niveles else False

        directos = []
        for r in mongo.db.rh.find({'JefeInmediato_id': {'$in': [str(eid), eid]}}, {'empleado_id': 1}):
            n, _ = nodo(r.get('empleado_id'))
            if n and not n['baja']:
                directos.append(n)
        directos.sort(key=lambda n: (n['Nombre'] + ' ' + n['ApelPaterno']).lower())

        # De arriba (el jefe más alto) hacia la persona.
        return jsonify({
            'superiores': list(reversed(superiores)),
            'actual':     actual,
            'directos':   directos,
            'hay_mas_arriba': hay_mas,
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
