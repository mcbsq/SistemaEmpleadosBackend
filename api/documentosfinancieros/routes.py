from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from bson.objectid import ObjectId
from .logic import create_documento, get_documentos_by_empleado, update_estado, delete_documento, get_doc_owner_info
from api.auth_decorators import require_roles, require_self_or_roles

# Reglas de negocio de este módulo (aplicadas dentro de los handlers, no solo
# por rol de ruta, porque dependen del `tipo` de documento):
#   - nómina:  solo ADMIN/SUPER_ADMIN la sube; el empleado solo consulta/descarga.
#   - CFDI:    el propio prestador de servicios la sube para que le paguen;
#              ADMIN/SUPER_ADMIN/CONTADOR la revisan, descargan y marcan "pagado".
#   - borrar:  ADMIN/SUPER_ADMIN siempre; el empleado solo su propio CFDI
#              mientras siga "pendiente" (ya pagado, queda como comprobante).


def setup_documentosfinancieros_routes(app, mongo):

    @app.route('/documentosfinancieros', methods=['POST'])
    @require_roles('EMPLOYEE', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR')
    def create_documento_route():
        data = request.get_json(silent=True) or {}
        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        own_empleado_id = identity.get('empleado_id') if isinstance(identity, dict) else None
        empleado_id = data.get('empleado_id') or own_empleado_id

        if role == 'EMPLOYEE':
            if data.get('tipo') != 'cfdi':
                return jsonify({'error': 'Solo puedes subir tus propias facturas (CFDI)'}), 403
            if str(empleado_id) != str(own_empleado_id):
                return jsonify({'error': 'No puedes subir documentos de otro empleado'}), 403
            # Solo prestadores de servicios profesionales facturan — un empleado
            # de nómina no emite CFDI, se le paga directo con recibo de nómina.
            rh = mongo.db.rh.find_one({'empleado_id': ObjectId(empleado_id)})
            if not rh or (rh.get('TipoRelacionLaboral') or 'nomina') != 'prestador_servicios':
                return jsonify({'error': 'Solo prestadores de servicios profesionales pueden subir CFDI'}), 403
        elif role == 'CONTADOR' and data.get('tipo') != 'nomina':
            return jsonify({'error': 'Contabilidad solo sube recibos de nómina'}), 403

        return create_documento(mongo, empleado_id, data, subido_por_role=role)

    @app.route('/documentosfinancieros/empleado/<empleado_id>', methods=['GET'])
    @require_self_or_roles('empleado_id', 'ADMIN', 'SUPER_ADMIN', 'CONTADOR')
    def get_documentos_by_empleado_route(empleado_id):
        return get_documentos_by_empleado(mongo, empleado_id)

    @app.route('/documentosfinancieros/<doc_id>/estado', methods=['PATCH'])
    @require_roles('ADMIN', 'SUPER_ADMIN', 'CONTADOR')
    def update_estado_route(doc_id):
        data = request.get_json(silent=True) or {}
        return update_estado(mongo, doc_id, data.get('estado'))

    @app.route('/documentosfinancieros/<doc_id>', methods=['DELETE'])
    @jwt_required()
    def delete_documento_route(doc_id):
        identity = get_jwt()
        role = identity.get('role') if isinstance(identity, dict) else None
        own_empleado_id = identity.get('empleado_id') if isinstance(identity, dict) else None

        if role in ('ADMIN', 'SUPER_ADMIN'):
            return delete_documento(mongo, doc_id)

        if role == 'EMPLOYEE':
            info = get_doc_owner_info(mongo, doc_id)
            if (info and info['empleado_id'] == str(own_empleado_id)
                    and info['tipo'] == 'cfdi' and info['estado'] == 'pendiente'):
                return delete_documento(mongo, doc_id)

        return jsonify({'error': 'Acceso no autorizado'}), 403
