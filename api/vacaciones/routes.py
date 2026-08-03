from flask import request, jsonify, Response
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask_jwt_extended import jwt_required, get_jwt
from .logic import (
    calcular_balance, crear_solicitud, get_solicitudes_por_empleado,
    get_pendientes, actualizar_estado,
)
from api.auth_decorators import require_roles, require_self_or_roles
from api.org.logic import get_vacaciones_config
from core.ics import evento_unico_ics


def _es_aprobador(mongo, role):
    if role in ("ADMIN", "SUPER_ADMIN"):
        return True
    cfg = get_vacaciones_config(mongo)
    return role in cfg.get("roles_aprueban", [])


def setup_vacaciones_routes(app, mongo):

    @app.route('/vacaciones/balance/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR')
    def balance_route(empleado_id):
        return calcular_balance(mongo, empleado_id)

    @app.route('/vacaciones', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR', 'PROJECT_MANAGER', 'JEFE_AREA', 'MEDICO')
    def crear_solicitud_route():
        data = request.get_json(silent=True) or {}
        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        own_empleado_id = identity.get('empleado_id') if isinstance(identity, dict) else None
        empleado_id = data.get('empleado_id') or own_empleado_id

        # Cualquiera puede pedir sus propias vacaciones; solo ADMIN/SUPER_ADMIN
        # pueden registrar una solicitud a nombre de otro (ej. vacaciones ya
        # acordadas verbalmente que hay que dejar en el sistema).
        if role not in ('ADMIN', 'SUPER_ADMIN') and str(empleado_id) != str(own_empleado_id):
            return jsonify({'error': 'No puedes solicitar vacaciones a nombre de otro empleado'}), 403

        return crear_solicitud(mongo, empleado_id, data, creado_por_role=role)

    @app.route('/vacaciones/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR')
    def solicitudes_por_empleado_route(empleado_id):
        return get_solicitudes_por_empleado(mongo, empleado_id)

    # Cola de aprobación: ADMIN/SUPER_ADMIN siempre, más quien esté configurado
    # en Configuración → Vacaciones → roles aprobadores.
    @app.route('/vacaciones/pendientes', methods=['GET'])
    @jwt_required()
    def pendientes_route():
        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        if not _es_aprobador(mongo, role):
            return jsonify({'error': 'Acceso no autorizado'}), 403
        return get_pendientes(mongo)

    @app.route('/vacaciones/<solicitud_id>/estado', methods=['PATCH'])
    @jwt_required()
    def actualizar_estado_route(solicitud_id):
        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        if not _es_aprobador(mongo, role):
            return jsonify({'error': 'Acceso no autorizado'}), 403
        data = request.get_json(silent=True) or {}
        revisor = identity.get('user') if isinstance(identity, dict) else 'desconocido'
        return actualizar_estado(mongo, solicitud_id, data.get('estado'), revisor, data.get('comentario', ''))

    @app.route('/vacaciones/<solicitud_id>/ics', methods=['GET'])
    @jwt_required()
    def descargar_ics_route(solicitud_id):
        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        own_empleado_id = identity.get('empleado_id') if isinstance(identity, dict) else None

        try:
            sid = ObjectId(solicitud_id)
        except (InvalidId, TypeError):
            return jsonify({'error': 'ID inválido'}), 400

        sol = mongo.db.vacaciones_solicitudes.find_one({'_id': sid})
        if not sol:
            return jsonify({'error': 'Solicitud no encontrada'}), 404
        if sol.get('estado') != 'aprobada':
            return jsonify({'error': 'Solo se puede exportar una solicitud aprobada'}), 400
        if role not in ('ADMIN', 'SUPER_ADMIN') and str(sol['empleado_id']) != str(own_empleado_id):
            return jsonify({'error': 'Acceso no autorizado'}), 403

        emp = mongo.db.empleados.find_one({'_id': sol['empleado_id']}) or {}
        nombre = f"{emp.get('Nombre','')} {emp.get('ApelPaterno','')}".strip() or "Empleado"
        ics = evento_unico_ics(
            titulo=f"Vacaciones — {nombre}",
            descripcion=f"Vacaciones aprobadas ({sol['dias_solicitados']} días).",
            fecha_inicio=sol['fecha_inicio'],
            fecha_fin=sol['fecha_fin'],
            uid=f"vacaciones-{solicitud_id}@sistemaempleados",
        )
        return Response(ics, mimetype='text/calendar', headers={
            'Content-Disposition': f'attachment; filename=vacaciones-{solicitud_id}.ics'
        })
