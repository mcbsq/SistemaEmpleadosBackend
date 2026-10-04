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


def acceso_perfil(mongo, identity, empleado_id):
    rels = relaciones(mongo, identity, empleado_id)
    ver, editar = set(), set()
    for r in rels:
        ver |= _MATRIZ[r]["ver"]
        editar |= _MATRIZ[r]["editar"]
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
