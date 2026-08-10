# api/conexiones_externas/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# CRUD de conexiones a sistemas externos (SUPER_ADMIN) + el endpoint que jala
# datos en vivo para mostrarlos en el perfil de un empleado. Aislado por
# tenant automáticamente (core/tenant_db.py) — cada empresa configura sus
# propias integraciones sin ver las de las demás.
from flask import jsonify
from bson.objectid import ObjectId
from bson.errors import InvalidId
import logging

from core.audit import registrar_auditoria
from core.conexiones_externas import (
    cifrar, consultar_sistema_externo, TIPOS_VALIDOS,
)

logger = logging.getLogger(__name__)

CAMPOS_MAPEO_VALIDOS = ("NumeroEmpleado", "email", "empleado_id")


def _serializar(doc):
    return {
        "_id": str(doc["_id"]),
        "nombre": doc.get("nombre"),
        "tipo": doc.get("tipo"),
        "base_url": doc.get("base_url"),
        "ruta_plantilla": doc.get("ruta_plantilla"),
        "esquema_auth": doc.get("esquema_auth", "Bearer"),
        "campo_mapeo": doc.get("campo_mapeo"),
        "activa": doc.get("activa", True),
        "creado_por": doc.get("creado_por"),
        "creado_en": doc.get("creado_en"),
        "api_key_preview": "•" * 10,  # nunca se manda la key real de vuelta
    }


def listar_conexiones(mongo):
    docs = list(mongo.db.conexiones_externas.find().sort("creado_en", -1))
    return jsonify([_serializar(d) for d in docs]), 200


def crear_conexion(mongo, data, identity):
    nombre = (data.get("nombre") or "").strip()
    tipo = data.get("tipo")
    base_url = (data.get("base_url") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    campo_mapeo = data.get("campo_mapeo")

    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400
    if tipo not in TIPOS_VALIDOS:
        return jsonify({"error": f"tipo debe ser uno de {TIPOS_VALIDOS}"}), 400
    if not base_url.startswith("http"):
        return jsonify({"error": "base_url debe ser una URL completa (https://...)"}), 400
    if not api_key:
        return jsonify({"error": "La API key del sistema externo es requerida"}), 400
    if campo_mapeo not in CAMPOS_MAPEO_VALIDOS:
        return jsonify({"error": f"campo_mapeo debe ser uno de {CAMPOS_MAPEO_VALIDOS}"}), 400

    from datetime import datetime, timezone
    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None

    doc = {
        "nombre": nombre[:120],
        "tipo": tipo,
        "base_url": base_url[:300],
        "ruta_plantilla": (data.get("ruta_plantilla") or "/{identificador}")[:200],
        "esquema_auth": (data.get("esquema_auth") or "Bearer")[:30],
        "campo_mapeo": campo_mapeo,
        "api_key_cifrada": cifrar(api_key),
        "activa": True,
        "creado_por": usuario,
        "creado_en": datetime.now(timezone.utc).isoformat(),
    }
    result = mongo.db.conexiones_externas.insert_one(doc)
    registrar_auditoria(mongo, usuario, role, "create", "conexiones_externas", str(result.inserted_id),
                         detalle=f"Conexión '{nombre}' ({tipo}) creada")

    return jsonify(_serializar({**doc, "_id": result.inserted_id})), 201


def actualizar_conexion(mongo, conexion_id, data, identity):
    try:
        cid = ObjectId(conexion_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    cambios = {}
    if "activa" in data:
        cambios["activa"] = bool(data["activa"])
    if "nombre" in data and data["nombre"]:
        cambios["nombre"] = data["nombre"][:120]
    if "base_url" in data and data["base_url"]:
        cambios["base_url"] = data["base_url"][:300]
    if "ruta_plantilla" in data and data["ruta_plantilla"]:
        cambios["ruta_plantilla"] = data["ruta_plantilla"][:200]
    if "campo_mapeo" in data and data["campo_mapeo"] in CAMPOS_MAPEO_VALIDOS:
        cambios["campo_mapeo"] = data["campo_mapeo"]
    if data.get("api_key"):
        cambios["api_key_cifrada"] = cifrar(data["api_key"])

    if not cambios:
        return jsonify({"error": "Nada que actualizar"}), 400

    result = mongo.db.conexiones_externas.update_one({"_id": cid}, {"$set": cambios})
    if result.matched_count == 0:
        return jsonify({"error": "Conexión no encontrada"}), 404

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "update", "conexiones_externas", conexion_id,
                         cambios={k: {"despues": v} for k, v in cambios.items() if k != "api_key_cifrada"})

    return jsonify({"message": "Conexión actualizada"}), 200


def eliminar_conexion(mongo, conexion_id, identity):
    try:
        cid = ObjectId(conexion_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    result = mongo.db.conexiones_externas.delete_one({"_id": cid})
    if result.deleted_count == 0:
        return jsonify({"error": "Conexión no encontrada"}), 404

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "delete", "conexiones_externas", conexion_id)

    return jsonify({"message": "Conexión eliminada"}), 200


def _valor_identificador(mongo, empleado_id, campo_mapeo):
    """Resuelve el valor que se manda al sistema externo, según el campo de
    mapeo configurado: NumeroEmpleado (de RH), email (de datos de contacto),
    o el propio empleado_id (Mongo) si el sistema externo ya lo conoce así."""
    if campo_mapeo == "empleado_id":
        return empleado_id
    if campo_mapeo == "NumeroEmpleado":
        rh = mongo.db.rh.find_one({"empleado_id": ObjectId(empleado_id)})
        return (rh or {}).get("NumeroEmpleado") or None
    if campo_mapeo == "email":
        dc = mongo.db.datoscontacto.find_one({"EmpleadoId": ObjectId(empleado_id)}) \
            or mongo.db.datoscontacto.find_one({"empleado_id": ObjectId(empleado_id)})
        return (dc or {}).get("ListaCorreos") or None
    return None


def obtener_nomina_externa(mongo, empleado_id):
    """
    Trae la nómina del empleado desde el sistema externo configurado (tipo
    "nomina"), en vivo — no se guarda copia local. Si no hay ninguna
    conexión activa de ese tipo, responde vacío (no es un error: la empresa
    simplemente no tiene esa integración configurada).
    """
    try:
        ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400

    conexion = mongo.db.conexiones_externas.find_one({"tipo": "nomina", "activa": True})
    if not conexion:
        return jsonify({"configurada": False}), 200

    identificador = _valor_identificador(mongo, empleado_id, conexion.get("campo_mapeo"))
    if not identificador:
        return jsonify({
            "configurada": True,
            "error": f"El empleado no tiene {conexion.get('campo_mapeo')} registrado — no se puede enlazar con el sistema externo.",
        }), 200

    datos, err = consultar_sistema_externo(conexion, str(identificador))
    if err:
        mensaje, status = err
        return jsonify({"configurada": True, "error": mensaje}), 200

    return jsonify({"configurada": True, "datos": datos, "fuente": conexion.get("nombre")}), 200
