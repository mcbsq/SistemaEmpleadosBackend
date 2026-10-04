# api/solicitudes_rh/routes.py
# ─────────────────────────────────────────────────────────────────────────────
# Canal directo empleado → Recursos Humanos desde su perfil (oct 2026): pedir
# una corrección de datos que solo RH puede hacer (sueldo, puesto, CURP…),
# una constancia, o simplemente preguntar. Cada solicitud queda registrada con
# su estado, RH recibe un aviso en la campana (y correo si hay SMTP) y el
# empleado recibe aviso cuando RH responde. Es la primera pieza de la
# bandeja de RH.
#   POST  /solicitudes-rh            el propio empleado crea una solicitud
#   GET   /solicitudes-rh/mias       las solicitudes del propio empleado
#   GET   /solicitudes-rh            RH: todas (filtro ?estado=)
#   PATCH /solicitudes-rh/<id>       RH: cambia estado y/o responde
# ─────────────────────────────────────────────────────────────────────────────
from datetime import datetime, timezone
import logging

from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt

from api.auth_decorators import require_roles
from api.notificaciones.logic import crear_notificacion
from core.mailer import send_generic_email
from core.visibilidad_perfil import ROLES_RH

logger = logging.getLogger(__name__)

TIPOS = {
    "correccion": "Corrección de datos",
    "constancia": "Constancia o documento",
    "duda":       "Duda o pregunta",
    "otro":       "Otro",
}
SECCIONES = {"personal", "laboral", "compensacion", "vacaciones", "salud", "documentos", "otro"}
ESTADOS = {"abierta", "en_proceso", "resuelta", "rechazada"}
ESTADO_TXT = {"abierta": "abierta", "en_proceso": "en proceso", "resuelta": "resuelta", "rechazada": "rechazada"}


def _ahora():
    return datetime.now(timezone.utc).isoformat()


def _serializar(doc):
    return {
        "_id": str(doc["_id"]),
        "empleado_id": str(doc.get("empleado_id") or ""),
        "empleado_nombre": doc.get("empleado_nombre", ""),
        "usuario": doc.get("usuario", ""),
        "tipo": doc.get("tipo"),
        "tipo_label": TIPOS.get(doc.get("tipo"), doc.get("tipo")),
        "seccion": doc.get("seccion"),
        "asunto": doc.get("asunto", ""),
        "mensaje": doc.get("mensaje", ""),
        "estado": doc.get("estado", "abierta"),
        "respuestas": doc.get("respuestas", []),
        "creado_en": doc.get("creado_en"),
        "actualizado_en": doc.get("actualizado_en"),
    }


def setup_solicitudes_rh_routes(app, mongo):

    @app.route('/solicitudes-rh', methods=['POST'])
    @jwt_required()
    def crear_solicitud_rh_route():
        identity = get_jwt()
        empleado_id = str(identity.get("empleado_id") or "")
        if not empleado_id:
            return jsonify({"error": "Tu cuenta no está ligada a un expediente de empleado."}), 400

        data = request.get_json(silent=True) or {}
        tipo = str(data.get("tipo") or "").strip()
        seccion = str(data.get("seccion") or "otro").strip()
        asunto = str(data.get("asunto") or "").strip()[:120]
        mensaje = str(data.get("mensaje") or "").strip()
        errores = {}
        if tipo not in TIPOS:
            errores["tipo"] = "Elige qué tipo de solicitud es."
        if seccion not in SECCIONES:
            seccion = "otro"
        if len(mensaje) < 5:
            errores["mensaje"] = "Cuéntale a RH un poco más (mínimo 5 caracteres)."
        if len(mensaje) > 2000:
            errores["mensaje"] = "Máximo 2000 caracteres."
        if errores:
            return jsonify({"error": "Revisa los datos marcados.", "campos": errores}), 400

        try:
            emp = mongo.db.empleados.find_one({"_id": ObjectId(empleado_id)}, {"Nombre": 1, "ApelPaterno": 1}) or {}
        except (InvalidId, TypeError):
            emp = {}
        nombre = f"{emp.get('Nombre', '')} {emp.get('ApelPaterno', '')}".strip() or identity.get("user", "")

        doc = {
            "empleado_id": empleado_id, "empleado_nombre": nombre, "usuario": identity.get("user"),
            "tipo": tipo, "seccion": seccion, "asunto": asunto or TIPOS[tipo], "mensaje": mensaje,
            "estado": "abierta", "respuestas": [], "creado_en": _ahora(), "actualizado_en": _ahora(),
        }
        res = mongo.db.solicitudes_rh.insert_one(doc)

        titulo = f"{nombre}: {doc['asunto']}"
        for admin in mongo.db.usuario.find({"role": {"$in": list(ROLES_RH)}}, {"user": 1, "email": 1}):
            crear_notificacion(mongo, admin.get("user"), "solicitud_rh", titulo, mensaje[:160], link="/solicitudes")
            if admin.get("email"):
                try:
                    send_generic_email(admin["email"], f"Nueva solicitud a RH — {titulo}",
                                       f"{nombre} escribió a RH ({TIPOS[tipo]}):\n\n{mensaje}")
                except Exception as e:
                    logger.warning(f"No se pudo enviar correo de solicitud RH: {e}")

        doc["_id"] = res.inserted_id
        return jsonify(_serializar(doc)), 201

    @app.route('/solicitudes-rh/mias', methods=['GET'])
    @jwt_required()
    def mis_solicitudes_rh_route():
        empleado_id = str(get_jwt().get("empleado_id") or "")
        if not empleado_id:
            return jsonify([]), 200
        docs = mongo.db.solicitudes_rh.find({"empleado_id": empleado_id}).sort("creado_en", -1)
        return jsonify([_serializar(d) for d in docs]), 200

    @app.route('/solicitudes-rh', methods=['GET'])
    @require_roles(*ROLES_RH)
    def solicitudes_rh_route():
        filtro = {}
        estado = request.args.get("estado")
        if estado in ESTADOS:
            filtro["estado"] = estado
        docs = mongo.db.solicitudes_rh.find(filtro).sort("creado_en", -1)
        return jsonify([_serializar(d) for d in docs]), 200

    @app.route('/solicitudes-rh/<solicitud_id>', methods=['PATCH'])
    @require_roles(*ROLES_RH)
    def actualizar_solicitud_rh_route(solicitud_id):
        identity = get_jwt()
        try:
            oid = ObjectId(solicitud_id)
        except (InvalidId, TypeError):
            return jsonify({"error": "ID inválido"}), 400
        sol = mongo.db.solicitudes_rh.find_one({"_id": oid})
        if not sol:
            return jsonify({"error": "Solicitud no encontrada"}), 404

        data = request.get_json(silent=True) or {}
        cambios = {"actualizado_en": _ahora()}
        estado = data.get("estado")
        if estado is not None:
            if estado not in ESTADOS:
                return jsonify({"error": "Estado inválido"}), 400
            cambios["estado"] = estado
        respuesta = str(data.get("respuesta") or "").strip()[:2000]
        update = {"$set": cambios}
        if respuesta:
            update["$push"] = {"respuestas": {"autor": identity.get("user"), "texto": respuesta, "fecha": _ahora()}}
        mongo.db.solicitudes_rh.update_one({"_id": oid}, update)

        if respuesta or estado:
            texto = respuesta or f"Tu solicitud ahora está {ESTADO_TXT.get(estado, estado)}."
            crear_notificacion(mongo, sol.get("usuario"), "solicitud_rh_respuesta",
                               f"RH respondió: {sol.get('asunto', '')}", texto[:160],
                               link=f"/Perfil/{sol.get('empleado_id')}?tab=solicitudes")
        return jsonify(_serializar(mongo.db.solicitudes_rh.find_one({"_id": oid}))), 200
