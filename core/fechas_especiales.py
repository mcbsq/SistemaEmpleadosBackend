# core/fechas_especiales.py
# ─────────────────────────────────────────────────────────────────────────────
# Cumpleaños y aniversarios se notifican DENTRO del sistema (no por .ics — eso
# se reservó para vacaciones aprobadas). Sin scheduler/cron en este backend,
# así que la verificación corre "perezosamente": se dispara en cada login,
# pero un flag con la fecha de la última corrida asegura que el escaneo real
# de empleados solo pase una vez por día sin importar cuántos logins entren.
from datetime import datetime, timezone, date
import logging

from api.notificaciones.logic import crear_notificacion

logger = logging.getLogger(__name__)


def _ya_corrio_hoy(mongo, hoy):
    flag = mongo.db.sistema_flags.find_one({"tipo": "fechas_especiales"})
    return flag and flag.get("ultima_corrida") == hoy


def _marcar_corrida(mongo, hoy):
    mongo.db.sistema_flags.update_one(
        {"tipo": "fechas_especiales"},
        {"$set": {"tipo": "fechas_especiales", "ultima_corrida": hoy}},
        upsert=True,
    )


def _admins_y_super(mongo):
    return [u.get("user") for u in mongo.db.usuario.find(
        {"role": {"$in": ["ADMIN", "SUPER_ADMIN"]}}, {"user": 1}
    ) if u.get("user")]


def verificar_fechas_especiales(mongo):
    try:
        hoy = date.today()
        hoy_iso = hoy.isoformat()
        if _ya_corrio_hoy(mongo, hoy_iso):
            return
        _marcar_corrida(mongo, hoy_iso)

        admins = _admins_y_super(mongo)

        # ── Cumpleaños ──────────────────────────────────────────────────
        for emp in mongo.db.empleados.find({"estado": {"$ne": "pendiente"}}):
            fec = emp.get("FecNacimiento")
            if not fec:
                continue
            try:
                nacimiento = datetime.strptime(fec[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if (nacimiento.month, nacimiento.day) != (hoy.month, hoy.day):
                continue

            nombre = f"{emp.get('Nombre','')} {emp.get('ApelPaterno','')}".strip() or "Un empleado"
            usuario_doc = mongo.db.usuario.find_one({"empleado_id": str(emp["_id"])})
            if usuario_doc and usuario_doc.get("user"):
                crear_notificacion(
                    mongo, usuario_doc["user"], "cumpleanos",
                    "¡Feliz cumpleaños! 🎂",
                    "Todo el equipo te desea un excelente día.",
                    link=f"/Perfil/{emp['_id']}",
                )
            for admin_user in admins:
                if usuario_doc and admin_user == usuario_doc.get("user"):
                    continue
                crear_notificacion(
                    mongo, admin_user, "cumpleanos_equipo",
                    "Cumpleaños en el equipo",
                    f"Hoy es el cumpleaños de {nombre}.",
                    link=f"/Perfil/{emp['_id']}",
                )

        # ── Aniversario laboral ─────────────────────────────────────────
        for rh in mongo.db.rh.find({"FechaIngreso": {"$exists": True, "$ne": ""}}):
            try:
                ingreso = datetime.strptime(rh["FechaIngreso"][:10], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if (ingreso.month, ingreso.day) != (hoy.month, hoy.day):
                continue
            anios = hoy.year - ingreso.year
            if anios < 1:
                continue

            emp = mongo.db.empleados.find_one({"_id": rh["empleado_id"]})
            if not emp:
                continue
            nombre = f"{emp.get('Nombre','')} {emp.get('ApelPaterno','')}".strip() or "Un empleado"
            usuario_doc = mongo.db.usuario.find_one({"empleado_id": str(emp["_id"])})
            plural = "año" if anios == 1 else "años"
            if usuario_doc and usuario_doc.get("user"):
                crear_notificacion(
                    mongo, usuario_doc["user"], "aniversario",
                    f"¡{anios} {plural} en la empresa! 🎉",
                    "Gracias por ser parte del equipo.",
                    link=f"/Perfil/{emp['_id']}",
                )
            for admin_user in admins:
                if usuario_doc and admin_user == usuario_doc.get("user"):
                    continue
                crear_notificacion(
                    mongo, admin_user, "aniversario_equipo",
                    "Aniversario laboral en el equipo",
                    f"Hoy {nombre} cumple {anios} {plural} en la empresa.",
                    link=f"/Perfil/{emp['_id']}",
                )
    except Exception as e:
        logger.error(f"verificar_fechas_especiales falló: {e}")
