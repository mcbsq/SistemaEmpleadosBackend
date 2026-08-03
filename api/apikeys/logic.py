from datetime import datetime, timezone
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import jsonify

from core.apikey_auth import generar_api_key

# Catálogo de scopes disponibles — crece según qué recursos se abran a
# consumo externo (hoy: /api/v1/empleados, /api/v1/rh, /api/v1/organigrama).
SCOPES_DISPONIBLES = [
    {"key": "empleados:read", "label": "Ver empleados"},
    {"key": "rh:read", "label": "Ver datos de RH"},
    {"key": "organigrama:read", "label": "Ver organigrama"},
]


def _serializar(doc):
    return {
        "_id": str(doc["_id"]),
        "nombre": doc.get("nombre"),
        "prefijo": doc.get("prefijo"),
        "scopes": doc.get("scopes", []),
        "creado_por": doc.get("creado_por"),
        "creado_en": doc.get("creado_en"),
        "ultimo_uso": doc.get("ultimo_uso"),
        "usos_totales": doc.get("usos_totales", 0),
        "activa": doc.get("activa", False),
    }


def listar_api_keys(mongo):
    docs = mongo.db.api_keys.find().sort("creado_en", -1)
    return jsonify([_serializar(d) for d in docs]), 200


def crear_api_key(mongo, data, creado_por):
    nombre = (data.get("nombre") or "").strip()
    scopes = data.get("scopes") or []
    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400
    if not scopes or not all(s in [x["key"] for x in SCOPES_DISPONIBLES] for s in scopes):
        return jsonify({"error": "Selecciona al menos un scope válido"}), 400

    plaintext, key_hash = generar_api_key()
    doc = {
        "nombre": nombre,
        "prefijo": plaintext[:14] + "…",
        "key_hash": key_hash,
        "scopes": scopes,
        "creado_por": creado_por,
        "creado_en": datetime.now(timezone.utc).isoformat(),
        "ultimo_uso": None,
        "activa": True,
    }
    result = mongo.db.api_keys.insert_one(doc)

    respuesta = _serializar({**doc, "_id": result.inserted_id})
    # Única vez que el plaintext viaja fuera del servidor.
    respuesta["key"] = plaintext
    return jsonify(respuesta), 201


def revocar_api_key(mongo, key_id):
    try:
        oid = ObjectId(key_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    result = mongo.db.api_keys.update_one({"_id": oid}, {"$set": {"activa": False}})
    if result.matched_count == 0:
        return jsonify({"error": "API key no encontrada"}), 404
    return jsonify({"message": "API key revocada"}), 200


def eliminar_api_key(mongo, key_id):
    try:
        oid = ObjectId(key_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    result = mongo.db.api_keys.delete_one({"_id": oid})
    if result.deleted_count == 0:
        return jsonify({"error": "API key no encontrada"}), 404
    return jsonify({"message": "API key eliminada"}), 200
