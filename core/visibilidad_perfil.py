# core/visibilidad_perfil.py
# ─────────────────────────────────────────────────────────────────────────────
# Matriz ÚNICA de quién ve / quién edita cada sección del perfil de un
# empleado. Antes la regla vivía repartida en decoradores sueltos y en el
# frontend (blur + "ingresa tu contraseña"), y un compañero podía revelar el
# contacto de otro escribiendo SU PROPIA contraseña. Ahora:
#   - el servidor decide aquí qué secciones corresponden a quien pregunta,
#   - las rutas de datos consultan esta misma matriz (require_seccion),
#   - el frontend solo pinta lo que GET /perfil/<id>/acceso le dice.
#
# Principio (ver Documentación/Estrategia_Observaciones_RH_2026-10.md):
#   A. Laboral/contractual    → solo RH edita; el empleado lo ve.
#   B. Compensación/bancarios → solo RH edita; el empleado ve lo suyo
#                               (bancarios enmascarados); Contador consulta.
#   C. Personales             → el empleado edita (RH recibe aviso).
#   D. Profesional/público    → el empleado edita; todos lo ven.
# ─────────────────────────────────────────────────────────────────────────────
from functools import wraps

from bson.objectid import ObjectId
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt

ROLES_RH = ("ADMIN", "SUPER_ADMIN", "RH")

SECCIONES = (
    "publico",       # nombre, foto, puesto, área, jefe, correo laboral
    "profesional",   # descripción, educación, experiencia, habilidades
    "contacto",      # teléfonos, correos personales, domicilio
    "emergencia",    # contactos de emergencia
    "laboral",       # horario, contrato, ingreso, núm. empleado, CURP/RFC/NSS
    "compensacion",  # salarios y datos bancarios
    "vacaciones",    # saldo, solicitudes, préstamos
    "clinico",       # expediente clínico
    "financiero",    # recibos de nómina / CFDI
)

# Qué ve y qué edita cada RELACIÓN entre quien mira y el perfil mirado. Una
# misma persona puede tener varias relaciones (ej. es Contador Y jefe directo):
# en ese caso se usa la unión.
_MATRIZ = {
    "rh": {
        "ver":    set(SECCIONES),
        "editar": set(SECCIONES),
    },
    "propio": {
        "ver":    set(SECCIONES),
        # Laboral y compensación los define la empresa, no el empleado.
        "editar": {"profesional", "contacto", "emergencia", "clinico", "financiero"},
    },
    "jefe": {
        # Necesita su horario y sus vacaciones para organizar al equipo, y a
        # quién llamar en una emergencia — pero NO cuánto gana.
        "ver":    {"publico", "profesional", "emergencia", "laboral", "vacaciones"},
        "editar": set(),
    },
    "medico": {
        "ver":    {"publico", "profesional", "emergencia", "clinico"},
        "editar": set(),
    },
    "contador": {
        "ver":    {"publico", "profesional", "laboral", "compensacion", "vacaciones", "financiero"},
        "editar": set(),
    },
    "companero": {
        "ver":    {"publico", "profesional"},
        "editar": set(),
    },
}

# Campos de RH que pertenecen a "compensacion" (se quitan si no se puede ver
# esa sección) y los bancarios que se enmascaran al propio empleado.
CAMPOS_COMPENSACION = (
    "Salario", "SalarioDiario", "SalarioDiarioIntegrado", "SalarioMensual",
    "Banco", "CLABE", "CuentaBancaria",
)
CAMPOS_BANCARIOS = ("CLABE", "CuentaBancaria")


def _str_id(valor):
    if valor is None:
        return ""
    if isinstance(valor, dict) and "$oid" in valor:
        return str(valor["$oid"])
    return str(valor)


def es_jefe_directo(mongo, jefe_empleado_id, empleado_id):
    """True si jefe_empleado_id figura como JefeInmediato_id del empleado."""
    if not jefe_empleado_id or not empleado_id:
        return False
    try:
        doc = mongo.db.rh.find_one(
            {"empleado_id": ObjectId(str(empleado_id))},
            {"JefeInmediato_id": 1},
        )
    except Exception:
        return False
    return bool(doc) and _str_id(doc.get("JefeInmediato_id")) == str(jefe_empleado_id)


def relaciones(mongo, identity, empleado_id):
    """Conjunto de relaciones de quien pregunta con el perfil empleado_id."""
    identity = identity if isinstance(identity, dict) else {}
    role = identity.get("role")
    propio_id = str(identity.get("empleado_id") or "")
    rels = set()

    if role in ROLES_RH:
        rels.add("rh")
    if propio_id and propio_id == str(empleado_id):
        rels.add("propio")
    if role == "MEDICO":
        rels.add("medico")
    if role == "CONTADOR":
        rels.add("contador")
    if propio_id and propio_id != str(empleado_id) and es_jefe_directo(mongo, propio_id, empleado_id):
        rels.add("jefe")
    if not rels:
        rels.add("companero")
    return rels


def permisos_de(mongo, identity):
    from core.permissions import get_permisos_for_role
    role = identity.get("role") if isinstance(identity, dict) else None
    return set(get_permisos_for_role(mongo, role))


def acceso_perfil(mongo, identity, empleado_id):
    rels = relaciones(mongo, identity, empleado_id)
    ver, editar = set(), set()
    for r in rels:
        ver |= _MATRIZ[r]["ver"]
        editar |= _MATRIZ[r]["editar"]
    # Un compañero sin otra relación ve lo profesional solo si su rol tiene
    # ese permiso de directorio (Gestión de roles → Directorio).
    if rels == {"companero"}:
        permisos = permisos_de(mongo, identity)
        if "*" not in permisos and "dir_profesional" not in permisos:
            ver.discard("profesional")
    return {
        "relaciones": sorted(rels),
        "ver":        {s: s in ver for s in SECCIONES},
        "editar":     {s: s in editar for s in SECCIONES},
    }


def puede(mongo, identity, empleado_id, seccion, accion="ver"):
    return acceso_perfil(mongo, identity, empleado_id)[accion].get(seccion, False)


def require_seccion(mongo, seccion, accion="ver", id_param="empleado_id"):
    """
    Decorador de ruta: exige JWT y que la matriz permita `accion` sobre
    `seccion` para el empleado de la URL (kwargs[id_param]).
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def wrapper(*args, **kwargs):
            empleado_id = kwargs.get(id_param)
            if not empleado_id or not puede(mongo, get_jwt(), empleado_id, seccion, accion):
                return jsonify({"error": "Acceso no autorizado"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _enmascarar(valor):
    texto = str(valor or "")
    if len(texto) <= 4:
        return texto
    return "•" * (len(texto) - 4) + texto[-4:]


def filtrar_rh(mongo, identity, empleado_id, doc):
    """
    Aplica la matriz a un documento de RH antes de responderlo:
    - sin "compensacion": se quitan salarios y bancarios;
    - propio empleado (sin rol RH/Contador): bancarios enmascarados.
    """
    if not isinstance(doc, dict):
        return doc
    acceso = acceso_perfil(mongo, identity, empleado_id)
    rels = set(acceso["relaciones"])
    if not acceso["ver"]["compensacion"]:
        for campo in CAMPOS_COMPENSACION:
            doc.pop(campo, None)
    elif "propio" in rels and not rels & {"rh", "contador"}:
        for campo in CAMPOS_BANCARIOS:
            if doc.get(campo):
                doc[campo] = _enmascarar(doc[campo])
    return doc


# ─── Directorio: lo que se ve de un compañero ────────────────────────────────
# Un empleado general necesita saber CÓMO contactar a alguien y SI ESTÁ
# disponible, no su vida personal. Cada bloque depende de un permiso del rol
# de quien mira (core/permissions.py::PERMISOS_DIRECTORIO); RH, el propio
# empleado y su jefe directo siempre lo ven completo.
def estado_actual(mongo, empleado_id, emp=None):
    """
    "baja" | "vacaciones" | "activo". Vacaciones = una solicitud aprobada que
    cubre el día de hoy (fechas YYYY-MM-DD); se devuelve también el regreso.
    """
    from datetime import date
    emp = emp or {}
    if emp.get("estado") == "baja":
        return {"estado": "baja"}
    hoy = date.today().isoformat()
    try:
        sol = mongo.db.vacaciones_solicitudes.find_one({
            "empleado_id": ObjectId(str(empleado_id)), "estado": "aprobada",
            "fecha_inicio": {"$lte": hoy}, "fecha_fin": {"$gte": hoy},
        })
    except Exception:
        sol = None
    if sol:
        return {"estado": "vacaciones", "hasta": sol.get("fecha_fin")}
    return {"estado": "activo"}


def tarjeta_directorio(mongo, identity, emp, rh=None, cuenta=None, contacto=None):
    """Tarjeta de un empleado, recortada según los permisos de quien mira."""
    rh, cuenta, contacto = rh or {}, cuenta or {}, contacto or {}
    eid = str(emp.get("_id"))
    rels = relaciones(mongo, identity, eid)
    permisos = permisos_de(mongo, identity)
    completo = "*" in permisos or bool(rels & {"rh", "propio", "jefe"})
    puede_ver = lambda p: completo or p in permisos  # noqa: E731

    fotos = emp.get("Fotografias") or []
    tarjeta = {
        "_id":             eid,
        "Nombre":          emp.get("Nombre", ""),
        "ApelPaterno":     emp.get("ApelPaterno", ""),
        "ApelMaterno":     emp.get("ApelMaterno", ""),
        "NombrePreferido": emp.get("NombrePreferido", ""),
        "Titular":         emp.get("Titular", ""),
        "Fotografias":     fotos[:1] if fotos else ([emp["Fotografia"]] if emp.get("Fotografia") else []),
        "visible":         sorted(p for p in ("dir_contacto", "dir_estado", "dir_puesto", "dir_profesional",
                                              "dir_cumpleanos", "dir_contacto_personal") if puede_ver(p)),
    }
    if puede_ver("dir_puesto"):
        depto = rh.get("Departamento") or emp.get("depto_id") or ""
        tarjeta.update({
            "Puesto":           rh.get("Puesto", ""),
            "Departamento":     "" if str(depto).strip().lower() == "sin asignar" else depto,
            "JefeInmediato":    rh.get("JefeInmediato", ""),
            "JefeInmediato_id": _str_id(rh.get("JefeInmediato_id")),
        })
    if puede_ver("dir_contacto"):
        tarjeta.update({
            # El correo de la cuenta de acceso es el de trabajo.
            "CorreoLaboral":    cuenta.get("email") or "",
            "TelefonoOficina":  rh.get("TelefonoOficina", ""),
            "Extension":        rh.get("Extension", ""),
            "UbicacionOficina": rh.get("UbicacionOficina", ""),
        })
    if puede_ver("dir_estado"):
        tarjeta.update(estado_actual(mongo, eid, emp))
    if puede_ver("dir_cumpleanos"):
        nac = str(emp.get("FecNacimiento") or "")[:10]
        tarjeta["Cumpleanos"] = nac[5:10] if len(nac) == 10 else ""  # MM-DD, nunca el año
    if puede_ver("dir_contacto_personal"):
        correos = contacto.get("ListaCorreos") or []
        principal = next((c for c in correos if isinstance(c, dict) and c.get("principal")), None) or (correos[0] if correos else None)
        tarjeta.update({
            "TelCelular":     contacto.get("TelCelular", ""),
            "CorreoPersonal": (principal.get("email") if isinstance(principal, dict) else principal) or "",
        })
    return tarjeta
