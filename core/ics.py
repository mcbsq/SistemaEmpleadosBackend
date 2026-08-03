# core/ics.py
# ─────────────────────────────────────────────────────────────────────────────
# Generador mínimo de archivos .ics (RFC 5545) — sin librería externa. Solo
# cubre lo que este sistema necesita: un evento puntual (vacaciones) o uno
# recurrente anual (cumpleaños, aniversario laboral).
import uuid
from datetime import datetime, timezone


def _escapar(texto):
    return (texto or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _dtstamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def evento_unico_ics(titulo, descripcion, fecha_inicio, fecha_fin, uid=None):
    """
    fecha_inicio/fecha_fin: 'YYYY-MM-DD'. Evento de día completo (DTEND es
    exclusivo en ICS, así que se suma 1 día).
    """
    fi = fecha_inicio.replace("-", "")
    ff_dt = datetime.strptime(fecha_fin, "%Y-%m-%d")
    ff = (ff_dt.replace(day=ff_dt.day)).strftime("%Y%m%d")
    # DTEND exclusivo → siguiente día del último día del evento
    from datetime import timedelta
    ff = (ff_dt + timedelta(days=1)).strftime("%Y%m%d")

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//SistemaEmpleados//ES\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid or uuid.uuid4()}\r\n"
        f"DTSTAMP:{_dtstamp()}\r\n"
        f"DTSTART;VALUE=DATE:{fi}\r\n"
        f"DTEND;VALUE=DATE:{ff}\r\n"
        f"SUMMARY:{_escapar(titulo)}\r\n"
        f"DESCRIPTION:{_escapar(descripcion)}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def evento_anual_ics(titulo, descripcion, mes, dia, uid=None):
    """Evento recurrente cada año en (mes, dia) — cumpleaños, aniversario."""
    anio_base = datetime.now().year
    fecha = f"{anio_base:04d}{mes:02d}{dia:02d}"
    from datetime import timedelta
    fecha_fin = (datetime.strptime(fecha, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//SistemaEmpleados//ES\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid or uuid.uuid4()}\r\n"
        f"DTSTAMP:{_dtstamp()}\r\n"
        f"DTSTART;VALUE=DATE:{fecha}\r\n"
        f"DTEND;VALUE=DATE:{fecha_fin}\r\n"
        "RRULE:FREQ=YEARLY\r\n"
        f"SUMMARY:{_escapar(titulo)}\r\n"
        f"DESCRIPTION:{_escapar(descripcion)}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
