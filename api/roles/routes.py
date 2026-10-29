from flask import request, jsonify
from flask_jwt_extended import get_jwt
import logging
import re
from api.auth_decorators import require_roles
from core.audit import registrar_auditoria
from core.permissions import PERMISOS_DEFAULT, config_roles

_NOMBRE_ROL_RE = re.compile(r"^[A-Z0-9_]{2,40}$")


def _actor():
    identity = get_jwt()
    if not isinstance(identity, dict):
        return None, None
    return identity.get('user'), identity.get('role')


def setup_roles_routes(app, mongo):

    def _guardar(cambios):
        mongo.db.roles_custom.update_one({'tipo': 'custom'}, {'$set': {'tipo': 'custom', **cambios}}, upsert=True)

    @app.route('/roles/custom', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_roles_custom():
        try:
            return jsonify(config_roles(mongo)['custom']), 200
        except Exception as e:
            logging.error(f"Error obteniendo roles custom: {e}")
            return jsonify([]), 200

    # Todo lo que Gestión de roles necesita en una sola llamada: roles
    # personalizados, roles de sistema eliminados y permisos editados.
    @app.route('/roles/config', methods=['GET'])
    @require_roles('ADMIN', 'SUPER_ADMIN')
    def get_roles_config():
        return jsonify(config_roles(mongo)), 200

    # Define los permisos disponibles en TODO el sistema — dejarlo abierto
    # (como estaba) equivale a que cualquiera pueda otorgarse cualquier
    # permiso a sí mismo. SUPER_ADMIN únicamente.
    @app.route('/roles/custom', methods=['POST'])
    @require_roles('SUPER_ADMIN')
    def save_roles_custom():
        try:
            data = request.get_json(silent=True) or []
            if not isinstance(data, list):
                return jsonify({'error': 'Se esperaba una lista de roles'}), 400
            cfg = config_roles(mongo)
            nombres = set()
            for r in data:
                nombre = str((r or {}).get('nombre') or '').strip().upper()
                if not _NOMBRE_ROL_RE.match(nombre):
                    return jsonify({'error': f'Nombre de rol inválido: "{nombre}". Usa letras, números y guion bajo.'}), 400
                if nombre in nombres:
                    return jsonify({'error': f'El rol {nombre} está repetido.'}), 400
                # Un nombre de sistema solo se reutiliza si la empresa ya
                # eliminó ese rol (es "recrearlo de cero").
                if nombre == 'SUPER_ADMIN' or (nombre in PERMISOS_DEFAULT and nombre not in cfg['sistema_eliminados']):
                    return jsonify({'error': f'{nombre} ya existe como rol del sistema. Elige otro nombre.'}), 409
                nombres.add(nombre)
                r['nombre'] = nombre

            _guardar({'roles': data})
            user, role = _actor()
            registrar_auditoria(mongo, user, role, 'update', 'roles_custom', None,
                                cambios={"roles": {"antes": cfg['custom'], "despues": data}})
            return jsonify({'message': 'Roles guardados', 'count': len(data)}), 200
        except Exception as e:
            logging.error(f"Error guardando roles custom: {e}")
            return jsonify({'error': str(e)}), 500

    # Permisos de un rol de sistema editados por la empresa. Antes vivían solo
    # en el localStorage del navegador del administrador y nunca llegaban al
    # login de nadie.
    @app.route('/roles/sistema/<rol>/permisos', methods=['PUT'])
    @require_roles('SUPER_ADMIN')
    def save_permisos_sistema(rol):
        if rol not in PERMISOS_DEFAULT or rol == 'SUPER_ADMIN':
            return jsonify({'error': 'Rol de sistema no válido'}), 400
        permisos = (request.get_json(silent=True) or {}).get('permisos')
        if not isinstance(permisos, list) or not all(isinstance(p, str) for p in permisos):
            return jsonify({'error': 'permisos debe ser una lista'}), 400
        cfg = config_roles(mongo)
        antes = cfg['permisos_sistema'].get(rol, PERMISOS_DEFAULT[rol])
        cfg['permisos_sistema'][rol] = sorted(set(permisos))
        _guardar({'permisos_sistema': cfg['permisos_sistema']})
        user, role = _actor()
        registrar_auditoria(mongo, user, role, 'update', 'roles_sistema', rol,
                            cambios={"permisos": {"antes": antes, "despues": cfg['permisos_sistema'][rol]}})
        return jsonify({'message': f'Permisos de {rol} actualizados', 'permisos': cfg['permisos_sistema'][rol]}), 200

    # Eliminar cualquier rol (de sistema o personalizado), salvo el
    # Administrador general. Si alguien lo tiene asignado, primero hay que
    # cambiarle el rol: una cuenta nunca se queda con un rol inexistente.
    @app.route('/roles/<nombre>', methods=['DELETE'])
    @require_roles('SUPER_ADMIN')
    def delete_rol(nombre):
        nombre = str(nombre or '').strip().upper()
        if nombre == 'SUPER_ADMIN':
            return jsonify({'error': 'El Administrador general no se puede eliminar.'}), 400
        en_uso = mongo.db.usuario.count_documents({'role': nombre})
        if en_uso:
            return jsonify({'error': f'{en_uso} cuenta(s) tienen este rol. Asígnales otro antes de eliminarlo.',
                            'usuarios': en_uso}), 409

        cfg = config_roles(mongo)
        custom = [r for r in cfg['custom'] if r.get('nombre') != nombre]
        era_custom = len(custom) != len(cfg['custom'])
        cambios = {}
        if era_custom:
            cambios['roles'] = custom
        elif nombre in PERMISOS_DEFAULT and nombre not in cfg['sistema_eliminados']:
            cambios['sistema_eliminados'] = cfg['sistema_eliminados'] + [nombre]
            cfg['permisos_sistema'].pop(nombre, None)
            cambios['permisos_sistema'] = cfg['permisos_sistema']
        else:
            return jsonify({'error': 'Rol no encontrado'}), 404

        _guardar(cambios)
        # Que tampoco siga apareciendo como "oculto" en la configuración.
        try:
            mongo.db.organizacion.update_one({}, {'$pull': {'roles_ocultos': nombre}})
        except Exception:
            pass
        user, role = _actor()
        registrar_auditoria(mongo, user, role, 'delete', 'rol', nombre,
                            detalle='Rol personalizado eliminado' if era_custom else 'Rol de sistema eliminado')
        return jsonify({'message': f'Rol {nombre} eliminado'}), 200
