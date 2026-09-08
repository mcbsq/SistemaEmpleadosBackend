# api/leads/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Solicitudes de información desde el sitio público (botones "Crear mi
# empresa" / "Comenzar ahora" de PublicLanding.jsx). A diferencia del alta
# de tenant en api/tenants/registration.py (que crea el espacio de inmediato),
# esto NO da de alta nada — solo captura nombre/correo/teléfono/notas y avisa
# por correo a contacto@redcibercom.com.mx para que Cibercom le dé seguimiento
# a mano. Pedido explícito del cliente (Observaciones Empleados 2026-09-03).
from datetime import datetime, timezone
import logging

from core.mailer import send_generic_email

logger = logging.getLogger(__name__)

CONTACTO_EMAIL = "contacto@redcibercom.com.mx"


def crear_lead(payload):
    nombre = (payload.get("nombre") or "").strip()
    correo = (payload.get("correo") or "").strip().lower()
    telefono = (payload.get("telefono") or "").strip()
    notas = (payload.get("notas") or "").strip()

    if not nombre or "@" not in correo or not telefono:
        return {"error": "invalid_lead"}, 400
    if len(nombre) > 150 or len(correo) > 150 or len(telefono) > 30 or len(notas) > 1000:
        return {"error": "invalid_lead"}, 400

    cuerpo = (
        f"Nueva solicitud de información desde el sitio de CibercomHR:\n\n"
        f"  Nombre:   {nombre}\n"
        f"  Correo:   {correo}\n"
        f"  Teléfono: {telefono}\n"
        f"  Notas:    {notas or '(sin notas)'}\n\n"
        f"  Recibido: {datetime.now(timezone.utc).isoformat()}\n"
    )
    enviado = send_generic_email(CONTACTO_EMAIL, f"Nueva solicitud — {nombre}", cuerpo)
    if not enviado:
        logger.error("No se pudo enviar la solicitud de %s <%s> a %s", nombre, correo, CONTACTO_EMAIL)
        return {"error": "email_delivery_failed"}, 503

    return {"ok": True}, 201
