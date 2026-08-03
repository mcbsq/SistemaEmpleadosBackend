from flask import request, jsonify
from api.auth_decorators import require_roles


def _serializar(doc):
    return {
        "_id": str(doc["_id"]),
        "usuario": doc.get("usuario"),
        "role": doc.get("role"),
        "accion": doc.get("accion"),
        "entidad": doc.get("entidad"),
        "entidad_id": doc.get("entidad_id"),
        "cambios": doc.get("cambios", {}),
        "detalle": doc.get("detalle"),
        "creado_en": doc.get("creado_en"),
    }


def setup_auditoria_routes(app, mongo):

    # Solo SUPER_ADMIN — el log de auditoría es en sí mismo un dato sensible
    # (revela quién cambió qué en toda la empresa).
    @app.route('/auditoria', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def listar_auditoria_route():
        query = {}
        entidad = request.args.get('entidad')
        usuario = request.args.get('usuario')
        if entidad:
            query['entidad'] = entidad
        if usuario:
            query['usuario'] = usuario

        try:
            limite = min(int(request.args.get('limite', 200)), 500)
        except ValueError:
            limite = 200

        docs = mongo.db.audit_log.find(query).sort("creado_en", -1).limit(limite)
        return jsonify([_serializar(d) for d in docs]), 200

    @app.route('/auditoria/entidades', methods=['GET'])
    @require_roles('SUPER_ADMIN')
    def listar_entidades_auditoria_route():
        entidades = mongo.db.audit_log.distinct("entidad")
        return jsonify(sorted(e for e in entidades if e)), 200
