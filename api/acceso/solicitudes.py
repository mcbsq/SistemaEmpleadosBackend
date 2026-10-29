# Cola local de solicitudes de acceso. No crea empresa, no llama a Aegis y
# no concede membresía. El operador de plataforma la revisa y, después, hace
# el alta en la consola de Aegis. Registrar aquí los UUID confirmados no
# marca el producto como listo ni abre datos.
import hashlib
import re
import uuid
from datetime import datetime, timezone

from flask import jsonify

from core.public_rate_limit import RegistrationRateLimiter

MENSAJE = (
    "Recibimos tu solicitud. El equipo revisará los datos y te indicará "
    "los siguientes pasos por correo."
)
ESTADOS = ("solicitada", "en_revision", "aprobada", "rechazada")
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_limite = RegistrationRateLimiter(max_attempts=5, window_seconds=3600)

# El cliente no puede pedir privilegios. Estos campos se rechazan.
_PROHIBIDOS = {"role", "rol", "password", "contrasena", "scopes", "plataforma", "tenant_id", "aegis_user_id"}


def _col(mongo):
    return mongo.db.raw.solicitudes_acceso


def _norm(texto, tope):
    return " ".join(str(texto or "").split())[:tope]


def _huella(ip, correo, empresa):
    base = f"{ip}|{correo}|{empresa}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()


def crear_solicitud(mongo, payload, ip, clave_idempotencia=None):
    payload = payload or {}
    if any(campo in payload for campo in _PROHIBIDOS):
        return jsonify({"error": "La solicitud no acepta rol, contraseña ni claves técnicas."}), 400
    empresa = _norm(payload.get("empresa") or payload.get("company_name"), 120)
    contacto = _norm(payload.get("contacto") or payload.get("contact_name"), 120)
    correo = _norm(payload.get("correo") or payload.get("email"), 254).lower()
    if len(empresa) < 2 or len(contacto) < 2 or not _CORREO.match(correo):
        return jsonify({"error": "Indica el nombre de la empresa, tu nombre y un correo válido."}), 400
    if not _limite.allow(f"ip:{ip}") or not _limite.allow(f"correo:{correo}"):
        return jsonify({"error": "Demasiadas solicitudes. Intenta más tarde."}), 429

    clave = _norm(clave_idempotencia, 80) or None
    huella_payload = hashlib.sha256(
        f"{empresa.lower()}|{contacto.lower()}|{correo}|empleados".encode("utf-8")
    ).hexdigest()
    ahora = datetime.now(timezone.utc).isoformat()
    doc = {
        "id_publico": uuid.uuid4().hex,
        "idempotencia": clave or f"fp:{huella_payload}",
        "fingerprint": huella_payload,
        "empresa": empresa,
        "empresa_norm": empresa.lower(),
        "contacto": contacto,
        "correo": correo,
        "producto": "empleados",
        "estado": "solicitada",
        "creado_en": ahora,
        "actualizado_en": ahora,
        "trazas": [{"en": ahora, "accion": "recibida", "ip_huella": _huella(ip, correo, empresa)}],
        "aegis_tenant_id": None,
        "aegis_user_id": None,
        "org_id_confirmado": None,
        "nota": "",
    }
    try:
        if clave:
            filtro = {"idempotencia": clave}
        else:
            filtro = {
                "correo": correo,
                "empresa_norm": empresa.lower(),
                "estado": {"$in": ["solicitada", "en_revision"]},
            }
        antes = _col(mongo).find_one_and_update(filtro, {"$setOnInsert": doc}, upsert=True)
        if antes:
            if (not clave) or antes.get("fingerprint") == huella_payload:
                return jsonify({"message": MENSAJE}), 202
            return jsonify({"error": "La solicitud no coincide con un envío ya recibido."}), 409
    except Exception as exc:
        if exc.__class__.__name__ == "DuplicateKeyError":
            previa = _col(mongo).find_one({"idempotencia": doc["idempotencia"]})
            if previa and previa.get("fingerprint") == huella_payload:
                return jsonify({"message": MENSAJE}), 202
            return jsonify({"error": "La solicitud no coincide con un envío ya recibido."}), 409
        return jsonify({"error": "El registro de solicitudes no está disponible. Intenta más tarde."}), 503
    _encolar_aviso(mongo, correo, empresa)
    return jsonify({"message": MENSAJE}), 202


def _encolar_aviso(mongo, correo, empresa):
    """Outbox. No envía correo: la notificación no es la persistencia."""
    import os
    destino = (os.environ.get("ACCESS_REQUEST_NOTIFY_EMAIL") or "").strip()
    if not destino:
        return
    try:
        _guardar_outbox(mongo, destino, correo, empresa)
    except Exception:
        return


def _guardar_outbox(mongo, destino, correo, empresa):
    dedup = _huella("aviso", correo, empresa)
    if mongo.db.raw.outbox_correo.find_one({"dedup": dedup, "estado": {"$in": ["pendiente", "enviado"]}}):
        return
    mongo.db.raw.outbox_correo.insert_one({
        "dedup": dedup,
        "destino": destino,
        "asunto": "Solicitud de acceso a Empleados",
        "estado": "pendiente",
        "intentos": 0,
        "creado_en": datetime.now(timezone.utc).isoformat(),
    })


def listar(mongo):
    filas = []
    for doc in _col(mongo).find({}):
        filas.append({
            "id": doc.get("id_publico"),
            "empresa": doc.get("empresa"),
            "contacto": doc.get("contacto"),
            "correo": doc.get("correo"),
            "producto": doc.get("producto"),
            "estado": doc.get("estado"),
            "creado_en": doc.get("creado_en"),
            "aegis_tenant_id": doc.get("aegis_tenant_id"),
            "aegis_user_id": doc.get("aegis_user_id"),
            "org_id_confirmado": doc.get("org_id_confirmado"),
            "nota": doc.get("nota") or "",
        })
    return filas


def marcar(mongo, id_publico, estado, nota="", identificadores=None, actor=""):
    if estado not in ("en_revision", "aprobada", "rechazada"):
        return jsonify({"error": "Estado no válido."}), 400
    doc = _col(mongo).find_one({"id_publico": id_publico})
    if not doc:
        return jsonify({"error": "Solicitud no encontrada."}), 404
    identificadores = identificadores or {}
    ahora = datetime.now(timezone.utc).isoformat()
    cambios = {
        "estado": estado,
        "actualizado_en": ahora,
        "nota": _norm(nota, 500),
    }
    if estado == "aprobada":
        # Solo se archivan los identificadores que el operador ya confirmó
        # en Aegis. No se crea usuario ni acceso.
        for origen, destino in (
            ("aegis_tenant_id", "aegis_tenant_id"),
            ("aegis_user_id", "aegis_user_id"),
            ("org_id", "org_id_confirmado"),
        ):
            valor = _norm(identificadores.get(origen), 80)
            if valor:
                cambios[destino] = valor
    traza = {"en": ahora, "accion": estado, "actor": actor}
    mongo.db.raw.solicitudes_acceso.update_one(
        {"id_publico": id_publico}, {"$set": cambios},
    )
    # $push puede no existir en el doble de pruebas; se reescribe la lista.
    actual = _col(mongo).find_one({"id_publico": id_publico}) or {}
    trazas = list(actual.get("trazas") or []) + [traza]
    _col(mongo).update_one({"id_publico": id_publico}, {"$set": {"trazas": trazas}})
    mongo.db.raw.auditoria.insert_one({
        "org_id": "plataforma",
        "usuario": actor,
        "accion": "resolver_solicitud_acceso",
        "entidad": "solicitud_acceso",
        "entidad_id": id_publico,
        "creado_en": ahora,
        "detalle": estado,
    })
    return jsonify({"id": id_publico, "estado": estado}), 200
