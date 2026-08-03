# api/rh/logic.py
from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import json
import logging

from core.audit import registrar_auditoria, diff_documentos

logger = logging.getLogger(__name__)


def _serialize(doc):
    if not doc:
        return None
    doc['_id']         = str(doc['_id'])
    doc['empleado_id'] = str(doc['empleado_id'])
    return doc


# Campos sensibles (financieros/identidad/documentos) que solo ADMIN,
# SUPER_ADMIN y CONTADOR (rol financiero) deben ver en el listado completo.
# PROJECT_MANAGER y JEFE_AREA acceden a esta misma ruta solo para puesto/
# departamento de su equipo — no deben recibir salario ni documentos.
_CAMPOS_SENSIBLES_RH = (
    "Salario", "CURP", "RFC", "ExpedienteDigitalPDF", "CamposPersonalizados",
)


# ── GET todos ─────────────────────────────────────────────────────────────────
def get_rhs(mongo, role=None):
    try:
        rh_list   = list(mongo.db.rh.find())
        empleados = {
            str(e['_id']): f"{e.get('Nombre','')} {e.get('ApelPaterno','')} {e.get('ApelMaterno','')}"
            for e in mongo.db.empleados.find()
        }
        redactar = role not in ("ADMIN", "SUPER_ADMIN", "CONTADOR")
        for doc in rh_list:
            doc['NombreCompleto'] = empleados.get(str(doc.get('empleado_id', '')), '')
            if redactar:
                for campo in _CAMPOS_SENSIBLES_RH:
                    doc.pop(campo, None)
        return Response(json_util.dumps(rh_list), mimetype="application/json")
    except Exception as e:
        logger.error(f"Error en get_rhs: {e}")
        return jsonify({'error': str(e)}), 500


# ── GET por empleado — usa Response+json.dumps para no truncar base64 ─────────
def get_rh_by_empleado_id(mongo, empleado_id):
    try:
        doc = mongo.db.rh.find_one({'empleado_id': ObjectId(empleado_id)})
        if not doc:
            return jsonify({}), 200
        serialized = _serialize(doc)
        # Usar json.dumps en lugar de jsonify para evitar truncamiento
        # de strings base64 largos (ExpedienteDigitalPDF puede ser varios MB)
        return Response(
            json.dumps(serialized, default=str),
            mimetype="application/json"
        )
    except (InvalidId, Exception) as e:
        return jsonify({'error': str(e)}), 500


# ── CREATE ────────────────────────────────────────────────────────────────────
def create_rh(mongo, empleado_id, rh_data):
    if not request.is_json:
        return jsonify({'error': 'No data provided'}), 400
    try:
        data    = request.get_json()
        eid     = ObjectId(data.get('empleado_id', empleado_id))
        payload = _build_payload(eid, data)
        result  = mongo.db.rh.insert_one(payload)
        return jsonify({'_id': str(result.inserted_id), 'message': 'RH creado'}), 201
    except Exception as e:
        logger.error(f"Error en create_rh: {e}")
        return jsonify({'error': str(e)}), 500


# ── UPDATE ────────────────────────────────────────────────────────────────────
def _filtrar_payload_por_presentes(payload, data):
    """
    Un PUT parcial (ej. solo {"Salario": 25000}) no debe borrar el resto del
    documento RH con los defaults de _build_payload — solo se aplican los
    campos que el caller realmente mandó.
    """
    SIMPLES = (
        'Puesto', 'JefeInmediato', 'JefeInmediato_id', 'HorarioLaboral',
        'NombreCompleto', 'Departamento', 'FechaIngreso', 'NumeroEmpleado',
        'CURP', 'RFC', 'EstadoCivil', 'Nacionalidad', 'Salario',
        'TipoRelacionLaboral',
    )
    out = {'empleado_id': payload['empleado_id']}
    for campo in SIMPLES:
        if campo in data:
            out[campo] = payload[campo]
    if 'ExpedienteDigitalPDF' in data:
        out['ExpedienteDigitalPDF'] = payload['ExpedienteDigitalPDF']
    if 'tipo_contrato' in data or 'contrato_firmado' in data:
        out['tipo_contrato'] = payload['tipo_contrato']
        out['contrato_firmado'] = payload['contrato_firmado']
    if 'CamposPersonalizados' in data:
        out['CamposPersonalizados'] = payload['CamposPersonalizados']
    return out


def update_rh(mongo, empleado_id, rh_data, identity=None):
    try:
        data    = request.get_json(silent=True) or {}
        eid     = ObjectId(empleado_id)
        payload = _filtrar_payload_por_presentes(_build_payload(eid, data), data)

        antes = mongo.db.rh.find_one({'empleado_id': eid}) or {}
        mongo.db.rh.update_one(
            {'empleado_id': eid},
            {'$set': payload},
            upsert=True,
        )

        cambios = diff_documentos(antes, {**antes, **payload})
        if cambios and isinstance(identity, dict):
            registrar_auditoria(mongo, identity.get('user'), identity.get('role'),
                                 'update', 'rh', empleado_id, cambios=cambios)

        return jsonify({'message': f'RH actualizado para empleado {empleado_id}'}), 200
    except (InvalidId, Exception) as e:
        logger.error(f"Error en update_rh: {e}")
        return jsonify({'error': str(e)}), 500


# ── DELETE ────────────────────────────────────────────────────────────────────
def delete_rh_by_empleado_id(mongo, empleado_id):
    try:
        result = mongo.db.rh.delete_one({'empleado_id': ObjectId(empleado_id)})
        if result.deleted_count > 0:
            return jsonify({'message': f'RH eliminado para empleado {empleado_id}'}), 200
        return jsonify({'error': 'No encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Helper interno ────────────────────────────────────────────────────────────
def _build_payload(eid, data):
    # Normalizar PDF — acepta array use-file-picker o string directo
    pdf_raw = data.get('ExpedienteDigitalPDF')
    if isinstance(pdf_raw, list) and len(pdf_raw) > 0:
        first = pdf_raw[0]
        pdf   = first.get('content') or first if isinstance(first, dict) else first
    elif isinstance(pdf_raw, str) and len(pdf_raw) > 0:
        pdf = pdf_raw  # ya viene como string (base64 o data URL), guardar tal cual
    else:
        pdf = None

    tipo_contrato    = data.get('tipo_contrato', '')
    contrato_firmado = data.get('contrato_firmado', False)
    if tipo_contrato in ('digital', 'autografa'):
        contrato_firmado = True

    # Campos personalizados: diccionario libre nombre→valor definido por el
    # admin desde el perfil ("toda la información que guste"). Se sanitiza a
    # strings con límites para que un cliente malicioso no infle el documento.
    campos_raw = data.get('CamposPersonalizados') or {}
    campos = {}
    if isinstance(campos_raw, dict):
        for k, v in list(campos_raw.items())[:40]:
            k = str(k).strip()[:60]
            if k:
                campos[k] = str(v).strip()[:500]

    return {
        'empleado_id':          eid,
        'Puesto':               data.get('Puesto',             ''),
        'JefeInmediato':        data.get('JefeInmediato',      ''),
        'JefeInmediato_id':     data.get('JefeInmediato_id',   ''),
        'HorarioLaboral':       data.get('HorarioLaboral', {
            'HoraEntrada':    '',
            'HoraSalida':     '',
            'TiempoComida':   '',
            'DiasTrabajados': '',
        }),
        'NombreCompleto':       data.get('NombreCompleto',     ''),
        'ExpedienteDigitalPDF': pdf,
        'contrato_firmado':     contrato_firmado,
        'tipo_contrato':        tipo_contrato,
        'Departamento':         data.get('Departamento',       ''),
        # ── Información laboral estándar (paridad con HRIS del mercado) ──
        'FechaIngreso':         data.get('FechaIngreso',       ''),
        'NumeroEmpleado':       data.get('NumeroEmpleado',     ''),
        'CURP':                 data.get('CURP',               ''),
        'RFC':                  data.get('RFC',                ''),
        'EstadoCivil':          data.get('EstadoCivil',        ''),
        'Nacionalidad':         data.get('Nacionalidad',       ''),
        'Salario':              data.get('Salario',            ''),
        'CamposPersonalizados': campos,
        # Determina qué sección financiera ve el empleado en su perfil:
        # "nomina" -> recibos de nómina (los sube RH); "prestador_servicios"
        # -> el propio empleado sube su CFDI para que le paguen.
        'TipoRelacionLaboral':  data.get('TipoRelacionLaboral', 'nomina'),
    }