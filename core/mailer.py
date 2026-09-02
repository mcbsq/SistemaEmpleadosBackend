# core/mailer.py
# ─────────────────────────────────────────────────────────────────────────────
# Envío de correos transaccionales por SMTP. Hoy solo se usa para entregar la
# contraseña temporal generada por Aegis al crear/resetear un usuario.
#
# Configuración por variables de entorno (todas opcionales; sin SMTP_HOST el
# envío queda deshabilitado y el backend devuelve la contraseña temporal en la
# respuesta HTTP como antes):
#   SMTP_HOST      p.ej. smtp.gmail.com
#   SMTP_PORT      default 587
#   SMTP_USER      usuario/login del servidor SMTP
#   SMTP_PASSWORD  contraseña o app-password
#   SMTP_FROM      remitente (default: SMTP_USER)
#   SMTP_TLS       default true (STARTTLS). Poner false solo en redes internas.
# ─────────────────────────────────────────────────────────────────────────────
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _truthy(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def mailer_enabled() -> bool:
    return bool((os.environ.get("SMTP_HOST") or "").strip())


def build_tenant_login_url(org_id: str = None) -> str:
    """Construye la liga pública sin fijar el dominio en el código."""
    origin = (os.environ.get("PUBLIC_APP_URL") or "https://cibercomrh.com").strip().rstrip("/")
    slug = (org_id or "").strip().strip("/")
    return f"{origin}/{slug}" if slug else f"{origin}/Login"


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
    if not mailer_enabled():
        return False

    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or user).strip()
    use_tls = _truthy(os.environ.get("SMTP_TLS"), True)

    msg = EmailMessage()
    msg["Subject"] = "Tu acceso a CibercomHR — contraseña temporal"
    msg["From"] = sender
    msg["To"] = to_email
    access_url = login_url or build_tenant_login_url()
    msg.set_content(
        f"Hola,\n\n"
        f"Se creó tu cuenta de acceso al sistema de empleados de Cibercom.\n\n"
        f"  Usuario:              {login_user}\n"
        f"  Contraseña temporal:  {temp_password}\n\n"
        f"  Liga de acceso:        {access_url}\n\n"
        f"Al iniciar sesión por primera vez el sistema te pedirá definir tu\n"
        f"contraseña definitiva (mínimo 12 caracteres).\n\n"
        f"Si no esperabas este correo, repórtalo a tu administrador de TI.\n"
    )

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        logger.info("Contraseña temporal enviada por correo a %s", to_email)
        return True
    except Exception as e:
        # Nunca registrar la contraseña; solo el destinatario y el error.
        logger.error("Fallo enviando correo a %s: %s", to_email, e)
        return False


def send_generic_email(to_email: str, asunto: str, cuerpo: str) -> bool:
    """
    Envío genérico para notificaciones del sistema (solicitudes de vacaciones,
    aprobaciones, etc.) que no involucran datos sensibles como contraseñas.
    """
    if not mailer_enabled():
        return False

    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or user).strip()
    use_tls = _truthy(os.environ.get("SMTP_TLS"), True)

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(cuerpo)

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
