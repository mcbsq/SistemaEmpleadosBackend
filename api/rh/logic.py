# api/rh/logic.py
from flask import jsonify, request, Response
from bson import json_util
from bson.objectid import ObjectId
from bson.errors import InvalidId
import json
import logging

from core.audit import registrar_auditoria, diff_documentos
from core.validadores_mx import validar_campos, normalizar, coherencia_identidad
from core.visibilidad_perfil import filtrar_rh, CAMPOS_COMPENSACION

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
    "CURP", "RFC", "NSS", "ExpedienteDigitalPDF", "CamposPersonalizados",
) + CAMPOS_COMPENSACION

# Días promedio por mes para pasar de salario diario a mensual (365 / 12).
DIAS_MES = 30.4


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
def get_rh_by_empleado_id(mongo, empleado_id, identity=None):
    try:
        doc = mongo.db.rh.find_one({'empleado_id': ObjectId(empleado_id)})
        if not doc:
            return jsonify({}), 200
        serialized = filtrar_rh(mongo, identity, empleado_id, _serialize(doc))
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
        'TipoRelacionLaboral', 'NSS', 'SalarioDiario', 'SalarioDiarioIntegrado',
        'Banco', 'CLABE', 'CuentaBancaria',
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


def _validar_puesto_catalogo(mongo, area, puesto):
    """Área y puesto salen del catálogo de Configuración → Áreas (oct 2026).
    Solo se valida cuando cambian, para no bloquear fichas con datos viejos
    capturados a mano antes del catálogo."""
    area, puesto = (area or '').strip(), (puesto or '').strip()
    if not area and not puesto:
        return {}
    cat = mongo.db.catalogodepto.find_one({'NombreDepto': area}) if area else None
    if not cat:
        return {'Departamento': 'Elige un área del catálogo.'}
    if puesto and puesto not in (cat.get('Puestos') or []):
        return {'Puesto': 'Elige un puesto que exista en esa área.'}
    return {}


def update_rh(mongo, empleado_id, rh_data, identity=None):
    try:
        data    = request.get_json(silent=True) or {}
        eid     = ObjectId(empleado_id)
        antes   = mongo.db.rh.find_one({'empleado_id': eid}) or {}

        # Solo se validan los identificadores que CAMBIAN: un dato viejo mal
        # capturado no debe impedir guardar el horario o el puesto.
        cambiados = {k: v for k, v in data.items() if normalizar(v) != normalizar(antes.get(k))}
        errores = validar_campos(cambiados)
        # Coherencia: CURP/RFC deben corresponder a ESTA persona (nombre,
        # apellidos, nacimiento). Solo si cambió alguno, por la misma razón.
        if not errores and ({'CURP', 'RFC'} & set(cambiados)):
            emp = mongo.db.empleados.find_one({'_id': eid}) or {}
            errores = coherencia_identidad(
                curp=data.get('CURP', antes.get('CURP')), rfc=data.get('RFC', antes.get('RFC')),
                nombre=emp.get('Nombre'), ap_paterno=emp.get('ApelPaterno'),
                ap_materno=emp.get('ApelMaterno'), fecha_nac=emp.get('FecNacimiento'))
        if not errores and ({'Puesto', 'Departamento'} & set(cambiados)):
            errores = _validar_puesto_catalogo(mongo, data.get('Departamento', antes.get('Departamento')),
                                               data.get('Puesto', antes.get('Puesto')))
        if errores:
            return jsonify({'error': 'Hay datos con formato inválido.', 'campos': errores}), 400
        _completar_salarios(data)
        payload = _filtrar_payload_por_presentes(_build_payload(eid, data), data)
        mongo.db.rh.update_one(
            {'empleado_id': eid},
            {'$set': payload},
            upsert=True,
        )

        # El área de la ficha laboral es la misma que usan la tabla de
        # Empleados, el organigrama y el alcance de los administradores de área.
        if 'Departamento' in cambiados and payload.get('Departamento'):
            mongo.db.empleados.update_one({'_id': eid}, {'$set': {'depto_id': payload['Departamento']}})

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
def _numero(valor):
    try:
        n = float(str(valor).replace(",", "").replace("$", "").strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _completar_salarios(data):
    """
    RH captura el salario DIARIO (la base legal en México). Si no manda el
    mensual, se calcula (diario × 30.4). El SDI depende del factor de
    integración (aguinaldo, prima vacacional y prestaciones de cada empresa),
    así que lo propone el frontend y RH lo confirma — aquí no se inventa.
    """
    diario = _numero(data.get('SalarioDiario'))
    if diario and not _numero(data.get('Salario')):
        data['Salario'] = round(diario * DIAS_MES, 2)



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
        'CURP':                 normalizar(data.get('CURP',    '')),
        'RFC':                  normalizar(data.get('RFC',     '')),
        'NSS':                  normalizar(data.get('NSS',     '')),
        'EstadoCivil':          data.get('EstadoCivil',        ''),
        'Nacionalidad':         data.get('Nacionalidad',       ''),
        # Salario = mensual (nombre histórico, lo consumen nómina y reportes).
        'Salario':              data.get('Salario',            ''),
        'SalarioDiario':        data.get('SalarioDiario',      ''),
        'SalarioDiarioIntegrado': data.get('SalarioDiarioIntegrado', ''),
        'Banco':                str(data.get('Banco', '') or '').strip()[:60],
        'CLABE':                normalizar(data.get('CLABE',   '')),
        'CuentaBancaria':       normalizar(data.get('CuentaBancaria', ''))[:20],
        'CamposPersonalizados': campos,
        # Régimen: "nomina" y "asimilados" -> la empresa timbra recibo de
        # nómina (lo sube RH); "prestador_servicios" (honorarios) -> el propio
        # empleado sube su CFDI/factura para que le paguen.
        'TipoRelacionLaboral':  data.get('TipoRelacionLaboral', 'nomina'),
    }