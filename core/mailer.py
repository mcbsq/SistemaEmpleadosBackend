# core/mailer.py
# ─────────────────────────────────────────────────────────────────────────────
# Envío de correos transaccionales: códigos de recuperación de contraseña,
# contraseñas temporales de altas y avisos (vacaciones, solicitudes…).
#
# Dos formas de enviar, por variables de entorno:
#   Resend (preferido)
#     RESEND_API_KEY  llave de https://resend.com
#     MAIL_FROM       remitente, p.ej. "CibercomHR <no-responder@redcibercom.com.mx>".
#                     El dominio debe estar verificado en Resend; sin dominio
#                     verificado Resend solo permite onboarding@resend.dev y
#                     solo entrega al correo del dueño de la cuenta.
#   SMTP (alternativa)
#     SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD,
#     SMTP_FROM (default SMTP_USER), SMTP_TLS (default true, STARTTLS)
# Sin ninguno de los dos el envío queda deshabilitado (mailer_enabled()).
# ─────────────────────────────────────────────────────────────────────────────
import html
import logging
import os
import smtplib
from email.message import EmailMessage

import requests

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
REMITENTE_RESEND_PRUEBAS = "CibercomHR <onboarding@resend.dev>"


def _truthy(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _resend_key():
    return (os.environ.get("RESEND_API_KEY") or "").strip()


def mailer_enabled() -> bool:
    return bool(_resend_key() or (os.environ.get("SMTP_HOST") or "").strip())


def build_tenant_login_url(org_id: str = None) -> str:
    """Construye la liga pública sin fijar el dominio en el código."""
    origin = (os.environ.get("PUBLIC_APP_URL") or "https://cibercomrh.com").strip().rstrip("/")
    slug = (org_id or "").strip().strip("/")
    return f"{origin}/{slug}" if slug else f"{origin}/Login"


def _enviar(to_email: str, asunto: str, texto: str, html_cuerpo: str = None) -> bool:
    """Envía un correo por Resend o SMTP. True si salió. Nunca registra el cuerpo."""
    if not mailer_enabled() or not to_email:
        return False

    if _resend_key():
        remitente = (os.environ.get("MAIL_FROM") or REMITENTE_RESEND_PRUEBAS).strip()
        payload = {"from": remitente, "to": [to_email], "subject": asunto, "text": texto}
        if html_cuerpo:
            payload["html"] = html_cuerpo
        try:
            r = requests.post(RESEND_URL, json=payload, timeout=15,
                              headers={"Authorization": f"Bearer {_resend_key()}"})
        except requests.RequestException as e:
            logger.error("Resend: error de red enviando a %s: %s", to_email, e)
            return False
        if r.status_code in (200, 201, 202):
            return True
        try:
            detalle = (r.json() or {}).get("message")
        except ValueError:
            detalle = r.text[:200]
        logger.error("Resend rechazó el correo a %s (HTTP %s): %s", to_email, r.status_code, detalle)
        return False

    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or os.environ.get("MAIL_FROM") or user).strip()
    use_tls = _truthy(os.environ.get("SMTP_TLS"), True)

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(texto)
    if html_cuerpo:
        msg.add_alternative(html_cuerpo, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        logger.error("Fallo enviando correo a %s: %s", to_email, e)
        return False


def send_temp_password_email(
    to_email: str,
    login_user: str,
    temp_password: str,
    login_url: str = None,
) -> bool:
    """
    Envía la contraseña temporal al correo del usuario recién creado/reseteado.
    Retorna True si el correo salió; False si el envío está deshabilitado o
    falló (el llamador decide el fallback — normalmente devolver la contraseña
    en la respuesta HTTP para que el admin la entregue en mano).
    """
    access_url = login_url or build_tenant_login_url()
    enviado = _enviar(
        to_email,
        "Tu acceso a CibercomHR — contraseña temporal",
        f"Hola,\n\n"
        f"Se creó tu cuenta de acceso al sistema de empleados de Cibercom.\n\n"
        f"  Usuario:              {login_user}\n"
        f"  Contraseña temporal:  {temp_password}\n\n"
        f"  Liga de acceso:        {access_url}\n\n"
        f"Al iniciar sesión por primera vez el sistema te pedirá definir tu\n"
        f"contraseña definitiva (mínimo 12 caracteres).\n\n"
        f"Si no esperabas este correo, repórtalo a tu administrador de TI.\n",
    )
    if enviado:
        logger.info("Contraseña temporal enviada por correo a %s", to_email)
    return enviado


def send_codigo_recuperacion(to_email: str, codigo: str, minutos: int) -> bool:
    """Código de un solo uso para "¿Olvidaste tu contraseña?"."""
    texto = (
        f"Hola,\n\n"
        f"Tu código para restablecer la contraseña de CibercomHR es:\n\n"
        f"    {codigo}\n\n"
        f"Vence en {minutos} minutos y solo sirve una vez.\n\n"
        f"Si no lo pediste, ignora este correo: tu contraseña no cambia.\n"
    )
    c = html.escape(codigo)
    cuerpo_html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;color:#1a1d2b">'
        '<h2 style="font-size:20px;margin:0 0 12px">Restablece tu contraseña</h2>'
        '<p style="margin:0 0 16px">Escribe este código en la ventana de CibercomHR:</p>'
        f'<p style="font-size:32px;font-weight:700;letter-spacing:8px;margin:0 0 16px">{c}</p>'
        f'<p style="margin:0 0 8px;color:#555">Vence en {minutos} minutos y solo sirve una vez.</p>'
        '<p style="margin:0;color:#555">Si no lo pediste, ignora este correo: tu contraseña no cambia.</p>'
        '</div>'
    )
    return _enviar(to_email, f"{codigo} es tu código de CibercomHR", texto, cuerpo_html)


def send_generic_email(to_email: str, asunto: str, cuerpo: str) -> bool:
    """
    Envío genérico para notificaciones del sistema (solicitudes de vacaciones,
    aprobaciones, etc.) que no involucran datos sensibles como contraseñas.
    """
    return _enviar(to_email, asunto, cuerpo)
