# core/aviso_cambios.py
# ─────────────────────────────────────────────────────────────────────────────
# Observación de RH (oct 2026): "solo RH debería editar la información de cada
# usuario, excepto los datos personales — avisar a RH cuando haya un cambio de
# datos personales". El empleado conserva el control de su teléfono, domicilio,
# contactos de emergencia y expediente clínico, pero RH se entera de cada
# cambio que haga él mismo (los que hace RH no generan aviso: ya lo sabe).
#
# El perfil se auto-guarda cada ~1 s mientras se escribe; para no inundar la
# campana con 20 avisos por una sola edición, los cambios del mismo empleado
# se agrupan en UNA notificación no leída por administrador durante 2 horas.
# ─────────────────────────────────────────────────────────────────────────────
from datetime import datetime, timedelta, timezone
from functools import wraps
import logging

from bson.objectid import ObjectId
from flask_jwt_extended import get_jwt

from core.audit import registrar_auditoria
from core.visibilidad_perfil import ROLES_RH

logger = logging.getLogger(__name__)

TIPO = "cambio_datos_personales"
VENTANA = timedelta(hours=2)

NOMBRES_SECCION = {
    "contacto":   "datos de contacto",
    "domicilio":  "domicilio",
    "emergencia": "contactos de emergencia",
    "clinico":    "expediente clínico",
}


def _nombre_empleado(mongo, empleado_id):
    try:
        emp = mongo.db.empleados.find_one({"_id": ObjectId(str(empleado_id))}, {"Nombre": 1, "ApelPaterno": 1})
    except Exception:
        emp = None
    if not emp:
        return "Un empleado"
    return f"{emp.get('Nombre', '')} {emp.get('ApelPaterno', '')}".strip() or "Un empleado"


def avisar_cambio_personal(mongo, identity, empleado_id, seccion):
    identity = identity if isinstance(identity, dict) else {}
    if identity.get("role") in ROLES_RH:
        return
    if str(identity.get("empleado_id") or "") != str(empleado_id):
        return

    etiqueta = NOMBRES_SECCION.get(seccion, seccion)
    nombre = _nombre_empleado(mongo, empleado_id)
    link = f"/Perfil/{empleado_id}"
    ahora = datetime.now(timezone.utc)
    desde = (ahora - VENTANA).isoformat()

    try:
        for admin in mongo.db.usuario.find({"role": {"$in": list(ROLES_RH)}}, {"user": 1}):
            usuario = admin.get("user")
            if not usuario:
                continue
            previa = mongo.db.notificaciones.find_one({
                "usuario": usuario, "tipo": TIPO, "link": link,
                "leida": False, "creado_en": {"$gte": desde},
            })
            if previa:
                secciones = list(dict.fromkeys((previa.get("secciones") or []) + [etiqueta]))
                mongo.db.notificaciones.update_one({"_id": previa["_id"]}, {"$set": {
                    "secciones": secciones,
                    "mensaje": f"Actualizó: {', '.join(secciones)}.",
                    "creado_en": ahora.isoformat(),
                }})
            else:
                mongo.db.notificaciones.insert_one({
                    "usuario": usuario, "tipo": TIPO,
                    "titulo": f"{nombre} cambió sus datos personales",
                    "mensaje": f"Actualizó: {etiqueta}.",
                    "secciones": [etiqueta], "link": link,
                    "leida": False, "creado_en": ahora.isoformat(),
                })
        registrar_auditoria(mongo, identity.get("user"), identity.get("role"), "update",
                            seccion, str(empleado_id), detalle="Cambio hecho por el propio empleado")
    except Exception as e:
        # Un aviso perdido no debe tumbar el guardado del empleado.
        logger.error(f"No se pudo avisar a RH del cambio personal ({seccion}): {e}")


def avisar_rh(mongo, seccion, id_param="empleado_id"):
    """Decorador para rutas PUT de datos personales: si respondió con éxito y
    quien cambió fue el propio empleado, avisa a RH."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resp = f(*args, **kwargs)
            status = resp[1] if isinstance(resp, tuple) and len(resp) > 1 else getattr(resp, "status_code", 200)
            if isinstance(status, int) and status < 300:
                avisar_cambio_personal(mongo, get_jwt(), kwargs.get(id_param), seccion)
            return resp
        return wrapper
    return decorator
