# api/notificaciones/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Notificaciones DENTRO del sistema — hoy varios módulos (vacaciones, etc.)
# solo mandaban correo; si el usuario no revisa su bandeja no se entera de
# nada dentro de la app. `crear_notificacion` es el punto único que los demás
# módulos deben llamar (además de, no en lugar de, el correo que ya mandan).
from datetime import datetime, timezone
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import jsonify
import logging

logger = logging.getLogger(__name__)


def _serializar(doc):
    return {
        "_id": str(doc["_id"]),
        "tipo": doc.get("tipo"),
        "titulo": doc.get("titulo"),
        "mensaje": doc.get("mensaje"),
        "link": doc.get("link"),
        "leida": doc.get("leida", False),
        "creado_en": doc.get("creado_en"),
    }


def crear_notificacion(mongo, usuario, tipo, titulo, mensaje, link=None):
    """
    Llamar desde cualquier módulo cuando pase algo que el usuario deba ver
    dentro del sistema (solicitud de vacaciones, préstamo aprobado, nómina
    publicada, etc.). No lanza si falla — una notificación perdida no debe
    tumbar el flujo principal que la origina.
    """
    if not usuario:
        return
    try:
        mongo.db.notificaciones.insert_one({
            "usuario": usuario,
            "tipo": tipo,
            "titulo": titulo,
            "mensaje": mensaje,
            "link": link,
            "leida": False,
            "creado_en": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"No se pudo crear notificación para {usuario}: {e}")


def listar_notificaciones(mongo, usuario, solo_no_leidas=False):
    query = {"usuario": usuario}
    if solo_no_leidas:
        query["leida"] = False
    docs = mongo.db.notificaciones.find(query).sort("creado_en", -1).limit(100)
    return jsonify([_serializar(d) for d in docs]), 200


def contar_no_leidas(mongo, usuario):
    count = mongo.db.notificaciones.count_documents({"usuario": usuario, "leida": False})
    return jsonify({"count": count}), 200


def marcar_leida(mongo, usuario, notif_id):
    try:
        oid = ObjectId(notif_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    result = mongo.db.notificaciones.update_one(
        {"_id": oid, "usuario": usuario},
        {"$set": {"leida": True}},
    )
    if result.matched_count == 0:
        return jsonify({"error": "Notificación no encontrada"}), 404
    return jsonify({"message": "Notificación marcada como leída"}), 200


def marcar_todas_leidas(mongo, usuario):
    mongo.db.notificaciones.update_many(
        {"usuario": usuario, "leida": False},
        {"$set": {"leida": True}},
    )
    return jsonify({"message": "Todas marcadas como leídas"}), 200


def eliminar_notificacion(mongo, usuario, notif_id):
    try:
        oid = ObjectId(notif_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    result = mongo.db.notificaciones.delete_one({"_id": oid, "usuario": usuario})
    if result.deleted_count == 0:
        return jsonify({"error": "Notificación no encontrada"}), 404
    return jsonify({"message": "Notificación eliminada"}), 200
