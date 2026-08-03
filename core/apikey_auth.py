# core/apikey_auth.py
# ─────────────────────────────────────────────────────────────────────────────
# Autenticación para el consumo EXTERNO del sistema (namespace /api/v1/...).
# Un programa externo nunca recibe un JWT de un usuario humano; en vez de eso
# manda una API key en el header "Authorization: ApiKey <key>". Solo el
# hash SHA-256 de la key vive en Mongo (colección `api_keys`) — el valor en
# texto plano se muestra una única vez, al crearla (mismo patrón que
# GitHub/Stripe), y no puede recuperarse después.
from functools import wraps
from collections import defaultdict, deque
from datetime import datetime, timezone
import hashlib
import secrets
import threading

from flask import request, jsonify

KEY_PREFIX = "sk_live_"

# Rate limit por key — ventana deslizante simple en memoria. No sobrevive un
# restart ni se comparte entre procesos, pero es suficiente para frenar un
# loop descontrolado del lado del consumidor externo durante pruebas/uso real
# de un solo proceso Flask (que es como corre hoy este backend).
_RATE_LIMIT_MAX = 120       # requests
_RATE_LIMIT_WINDOW = 60.0   # segundos
_rate_buckets = defaultdict(deque)
_rate_lock = threading.Lock()


def _rate_limited(key_hash):
    import time
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[key_hash]
        while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_MAX:
            return True
        bucket.append(now)
        return False


def _hash_key(plaintext_key):
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()


def generar_api_key():
    """Devuelve (plaintext, hash). El plaintext solo se retorna aquí, una vez."""
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, _hash_key(plaintext)


def _extraer_key_del_header():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("ApiKey "):
        return auth[len("ApiKey "):].strip()
    return None


def require_api_key(mongo, *scopes_validos):
    """
    Uso: @require_api_key(mongo, 'empleados:read')
    Verifica la API key del header contra `api_keys` (por hash, nunca en
    texto plano), exige que esté activa y que tenga al menos uno de los
    scopes pedidos, y registra `ultimo_uso`.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            plaintext = _extraer_key_del_header()
            if not plaintext:
                return jsonify({
                    "error": "Falta API key (header Authorization: ApiKey <key>)",
                    "code": "missing_key",
                }), 401

            key_hash = _hash_key(plaintext)
            doc = mongo.db.api_keys.find_one({"key_hash": key_hash})
            if not doc or not doc.get("activa", False):
                return jsonify({"error": "API key inválida o revocada", "code": "invalid_key"}), 401

            if _rate_limited(key_hash):
                return jsonify({
                    "error": f"Límite de {_RATE_LIMIT_MAX} solicitudes/minuto excedido para esta API key",
                    "code": "rate_limited",
                }), 429

            # Sin scopes exigidos (ej. /api/v1/ping): cualquier key activa pasa —
            # solo sirve para confirmar que la key en sí es válida.
            if scopes_validos:
                scopes = doc.get("scopes", [])
                if "*" not in scopes and not any(s in scopes for s in scopes_validos):
                    return jsonify({
                        "error": "Esta API key no tiene permiso para este recurso",
                        "code": "forbidden_scope",
                    }), 403

            mongo.db.api_keys.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {"ultimo_uso": datetime.now(timezone.utc).isoformat()},
                    "$inc": {"usos_totales": 1},
                },
            )
            return f(*args, **kwargs)
        return wrapper
    return decorator
