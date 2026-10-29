from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt

from api.tenants.routes import es_operador_plataforma
from core.client_ip import ip_cliente
from .solicitudes import crear_solicitud, listar, marcar


def setup_acceso_routes(app, mongo):

    @app.route("/public/access-requests", methods=["POST"])
    def solicitar_acceso():
        cuerpo = request.get_json(silent=True) or {}
        clave = request.headers.get("Idempotency-Key")
        respuesta, status = crear_solicitud(mongo, cuerpo, ip_cliente(request), clave)
        return respuesta, status

    def _operador():
        claims = get_jwt()
        if not es_operador_plataforma(claims):
            return None
        return claims

    @app.route("/admin/access-requests", methods=["GET"])
    @jwt_required()
    def listar_solicitudes():
        if not _operador():
            return jsonify({"error": "Acceso no autorizado"}), 403
        return jsonify(listar(mongo)), 200

    @app.route("/admin/access-requests/<id_publico>", methods=["POST"])
    @jwt_required()
    def resolver_solicitud(id_publico):
        claims = _operador()
        if not claims:
            return jsonify({"error": "Acceso no autorizado"}), 403
        cuerpo = request.get_json(silent=True) or {}
        respuesta, status = marcar(
            mongo, id_publico, cuerpo.get("estado") or "",
            nota=cuerpo.get("nota") or "",
            identificadores=cuerpo.get("identificadores") or {},
            actor=claims.get("user") or "",
        )
        return respuesta, status
