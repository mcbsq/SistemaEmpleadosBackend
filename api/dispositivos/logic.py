# api/dispositivos/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Dispositivos de confianza (oct 2026) — "entrar con Face ID / huella" en la
# app móvil, como las apps de banco:
#   1. Tras un login normal, la app registra el celular y recibe una llave
#      propia del dispositivo (larga, aleatoria). La app la guarda en el
#      almacenamiento seguro del teléfono (Llavero / Keystore), protegida por
#      la biometría o el desbloqueo del celular. La contraseña NUNCA se guarda.
#   2. Al abrir la app, el teléfono pide Face ID / huella / patrón para
#      liberar la llave y la app la cambia aquí por una sesión nueva (JWT).
#   3. La llave rota en cada uso (una robada y ya usada deja de servir) y se
#      puede revocar: al cerrar sesión, al cambiar o restablecer contraseña, o
#      desde Cuentas (p. ej. si alguien pierde su teléfono).
# En la base solo se guarda el hash SHA-256 de la llave, nunca la llave.
# ─────────────────────────────────────────────────────────────────────────────
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone

from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import g, jsonify

logger = logging.getLogger(__name__)

MAX_DISPOSITIVOS_POR_CUENTA = 5


def _ahora():
    return datetime.now(timezone.utc).isoformat()


def _hash(llave):
    return hashlib.sha256(llave.encode("utf-8")).hexdigest()


def _nueva_llave():
    return secrets.token_urlsafe(48)


def _publico(d):
    return {
        "_id": str(d["_id"]),
        "nombre": d.get("nombre") or "Celular",
        "plataforma": d.get("plataforma") or "",
        "creado_en": d.get("creado_en"),
        "ultimo_uso": d.get("ultimo_uso"),
    }


def registrar(mongo, claims, data):
    """Registra el celular de la sesión actual y regresa su llave (una sola vez)."""
    user = claims.get("user")
    org_id = claims.get("org_id")
    if not user or not org_id:
        return jsonify({"error": "Sesión inválida"}), 401
    if getattr(g, "modo_soporte", False):
        return jsonify({"error": "No disponible en modo soporte."}), 403

    nombre = " ".join(str(data.get("nombre") or "Celular").split())[:60]
    plataforma = str(data.get("plataforma") or "")[:20]
    llave = _nueva_llave()
    doc = {
        "user": user, "org_id": org_id, "nombre": nombre, "plataforma": plataforma,
        "llave_hash": _hash(llave), "creado_en": _ahora(), "ultimo_uso": None, "revocado": False,
    }
    ins = mongo.db.raw.dispositivos.insert_one(doc)

    # Máximo N celulares activos por cuenta: se revocan los más viejos.
    activos = list(mongo.db.raw.dispositivos.find(
        {"user": user, "org_id": org_id, "revocado": False}, {"_id": 1}).sort("creado_en", -1))
    for viejo in activos[MAX_DISPOSITIVOS_POR_CUENTA:]:
        mongo.db.raw.dispositivos.update_one({"_id": viejo["_id"]}, {"$set": {"revocado": True, "revocado_en": _ahora(), "motivo": "límite"}})

    return jsonify({"dispositivo_id": str(ins.inserted_id), "llave": llave}), 201


def entrar(mongo, data, emitir_sesion):
    """Cambia la llave del dispositivo por una sesión nueva. La llave rota."""
    dispositivo_id = str(data.get("dispositivo_id") or "")
    llave = str(data.get("llave") or "")
    try:
        oid = ObjectId(dispositivo_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "Dispositivo no reconocido. Inicia sesión de nuevo."}), 401

    disp = mongo.db.raw.dispositivos.find_one({"_id": oid})
    if not disp or disp.get("revocado") or not llave or not hmac.compare_digest(disp.get("llave_hash", ""), _hash(llave)):
        return jsonify({"error": "Dispositivo no reconocido. Inicia sesión de nuevo."}), 401

    usuario = mongo.db.raw.usuario.find_one({"user": disp["user"]})
    # Cuentas legacy sin org_id migrado pertenecen a Cibercom (igual que el login).
    if usuario and (usuario.get("org_id") or "cibercom") != disp["org_id"]:
        usuario = None
    if not usuario or usuario.get("activo") is False:
        mongo.db.raw.dispositivos.update_one({"_id": oid}, {"$set": {"revocado": True, "revocado_en": _ahora(), "motivo": "cuenta inexistente"}})
        return jsonify({"error": "Tu cuenta ya no está disponible. Inicia sesión de nuevo."}), 401

    # A partir de aquí la sesión pertenece a esa empresa (aislamiento por tenant).
    g.org_id = disp["org_id"]
    nueva = _nueva_llave()
    mongo.db.raw.dispositivos.update_one({"_id": oid}, {"$set": {"llave_hash": _hash(nueva), "ultimo_uso": _ahora()}})

    resp, status = emitir_sesion(mongo, usuario, disp["user"], org_id=disp["org_id"])
    if status != 200:
        return resp, status
    cuerpo = resp.get_json()
    cuerpo["llave"] = nueva
    return jsonify(cuerpo), 200


def revocar_de_usuario(mongo, user, org_id, motivo):
    """Revoca todos los celulares de una cuenta (cambio/restablecimiento de contraseña)."""
    r = mongo.db.raw.dispositivos.update_many(
        {"user": user, "org_id": org_id, "revocado": False},
        {"$set": {"revocado": True, "revocado_en": _ahora(), "motivo": motivo}},
    )
    return r.modified_count


def listar(mongo, user, org_id):
    docs = mongo.db.raw.dispositivos.find({"user": user, "org_id": org_id, "revocado": False}).sort("creado_en", -1)
    return [_publico(d) for d in docs]


def revocar_uno(mongo, dispositivo_id, user, org_id):
    try:
        oid = ObjectId(dispositivo_id)
    except (InvalidId, TypeError):
        return 0
    r = mongo.db.raw.dispositivos.update_one(
        {"_id": oid, "user": user, "org_id": org_id, "revocado": False},
        {"$set": {"revocado": True, "revocado_en": _ahora(), "motivo": "cerró sesión"}},
    )
    return r.modified_count
