# api/desempeno/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Evaluaciones de desempeño: ciclos periódicos con autoevaluación + evaluación
# del jefe, y metas simples con % de cumplimiento — patrón de mercado
# (Lattice/15Five simplificado, sin integraciones de calendario/Slack).
from datetime import datetime, timezone
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import jsonify
import logging

from core.audit import registrar_auditoria

logger = logging.getLogger(__name__)

# Competencias estándar de evaluación de desempeño — el mismo set que usan
# herramientas de mercado (Lattice, 15Five, BambooHR) en su plantilla por
# defecto. Cada una se califica 1-5; el puntaje general es su promedio.
CRITERIOS_DESEMPENO = [
    {"id": "calidad",        "nombre": "Calidad de trabajo"},
    {"id": "productividad",  "nombre": "Productividad"},
    {"id": "comunicacion",   "nombre": "Comunicación"},
    {"id": "trabajo_equipo", "nombre": "Trabajo en equipo"},
    {"id": "puntualidad",    "nombre": "Puntualidad y asistencia"},
    {"id": "iniciativa",     "nombre": "Iniciativa y proactividad"},
    {"id": "conocimiento",   "nombre": "Conocimiento técnico"},
    {"id": "adaptabilidad",  "nombre": "Adaptabilidad al cambio"},
]
_IDS_CRITERIOS = {c["id"] for c in CRITERIOS_DESEMPENO}


def _procesar_criterios(data_criterios):
    """
    Valida y limpia la lista de criterios calificados; retorna (criterios, puntaje_promedio).
    Solo se aceptan los ids del catálogo estándar, puntaje 1-5.
    """
    criterios = []
    if isinstance(data_criterios, list):
        for c in data_criterios:
            cid = c.get("id")
            if cid not in _IDS_CRITERIOS:
                continue
            try:
                p = int(c.get("puntaje"))
                if not (1 <= p <= 5):
                    continue
            except (TypeError, ValueError):
                continue
            criterios.append({"id": cid, "puntaje": p})
    puntaje_promedio = round(sum(c["puntaje"] for c in criterios) / len(criterios)) if criterios else None
    return criterios, puntaje_promedio


def _serializar_ciclo(doc):
    return {
        "_id": str(doc["_id"]),
        "nombre": doc.get("nombre"),
        "fecha_inicio": doc.get("fecha_inicio"),
        "fecha_fin": doc.get("fecha_fin"),
        "estado": doc.get("estado", "activo"),
        "creado_por": doc.get("creado_por"),
        "creado_en": doc.get("creado_en"),
    }


def _serializar_evaluacion(doc):
    return {
        "_id": str(doc["_id"]),
        "ciclo_id": str(doc["ciclo_id"]),
        "empleado_id": str(doc["empleado_id"]),
        "metas": doc.get("metas", []),
        "autoevaluacion": doc.get("autoevaluacion", {"puntaje": None, "criterios": [], "comentario": "", "completada": False}),
        "evaluacion_jefe": doc.get("evaluacion_jefe", {"puntaje": None, "criterios": [], "comentario": "", "completada": False, "evaluador": None}),
        "creado_en": doc.get("creado_en"),
    }


def listar_ciclos(mongo):
    docs = list(mongo.db.ciclos_evaluacion.find().sort("creado_en", -1))
    return jsonify([_serializar_ciclo(d) for d in docs]), 200


def crear_ciclo(mongo, data, identity):
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre del ciclo es requerido"}), 400

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None

    doc = {
        "nombre": nombre[:150],
        "fecha_inicio": data.get("fecha_inicio", ""),
        "fecha_fin": data.get("fecha_fin", ""),
        "estado": "activo",
        "creado_por": usuario,
        "creado_en": datetime.now(timezone.utc).isoformat(),
    }
    result = mongo.db.ciclos_evaluacion.insert_one(doc)
    ciclo_id = result.inserted_id

    # Genera una evaluación (vacía) por cada empleado activo — así ni el
    # empleado ni el jefe tienen que "crear" nada, solo llenar lo que ya existe.
    empleados = list(mongo.db.empleados.find({"estado": {"$ne": "pendiente"}}, {"_id": 1}))
    if empleados:
        ahora = datetime.now(timezone.utc).isoformat()
        mongo.db.evaluaciones.insert_many([
            {
                "ciclo_id": ciclo_id,
                "empleado_id": e["_id"],
                "metas": [],
                "autoevaluacion": {"puntaje": None, "criterios": [], "comentario": "", "completada": False},
                "evaluacion_jefe": {"puntaje": None, "criterios": [], "comentario": "", "completada": False, "evaluador": None},
                "creado_en": ahora,
            }
            for e in empleados
        ])

    registrar_auditoria(mongo, usuario, role, "create", "ciclos_evaluacion", str(ciclo_id),
                         detalle=f"{nombre} — {len(empleados)} evaluaciones generadas")

    return jsonify(_serializar_ciclo({**doc, "_id": ciclo_id})), 201


def cerrar_ciclo(mongo, ciclo_id, identity):
    try:
        cid = ObjectId(ciclo_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    result = mongo.db.ciclos_evaluacion.update_one({"_id": cid}, {"$set": {"estado": "cerrado"}})
    if result.matched_count == 0:
        return jsonify({"error": "Ciclo no encontrado"}), 404

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "update", "ciclos_evaluacion", ciclo_id,
                         cambios={"estado": {"antes": "activo", "despues": "cerrado"}})

    return jsonify({"message": "Ciclo cerrado"}), 200


def listar_evaluaciones_ciclo(mongo, ciclo_id):
    try:
        cid = ObjectId(ciclo_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    docs = list(mongo.db.evaluaciones.find({"ciclo_id": cid}))
    empleados = {
        str(e["_id"]): f"{e.get('Nombre','')} {e.get('ApelPaterno','')}".strip()
        for e in mongo.db.empleados.find({}, {"Nombre": 1, "ApelPaterno": 1})
    }
    out = []
    for d in docs:
        s = _serializar_evaluacion(d)
        s["empleado_nombre"] = empleados.get(s["empleado_id"], "")
        out.append(s)
    return jsonify(out), 200


def get_evaluacion(mongo, evaluacion_id):
    try:
        eid = ObjectId(evaluacion_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    doc = mongo.db.evaluaciones.find_one({"_id": eid})
    if not doc:
        return jsonify({"error": "Evaluación no encontrada"}), 404
    return jsonify(_serializar_evaluacion(doc)), 200


def get_evaluacion_activa_empleado(mongo, empleado_id):
    """La evaluación del ciclo activo más reciente para este empleado (o None)."""
    try:
        emp_oid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    ciclo = mongo.db.ciclos_evaluacion.find_one({"estado": "activo"}, sort=[("creado_en", -1)])
    if not ciclo:
        return jsonify(None), 200

    doc = mongo.db.evaluaciones.find_one({"ciclo_id": ciclo["_id"], "empleado_id": emp_oid})
    if not doc:
        return jsonify(None), 200
    return jsonify(_serializar_evaluacion(doc)), 200


def guardar_metas(mongo, evaluacion_id, metas, identity):
    try:
        eid = ObjectId(evaluacion_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    if not isinstance(metas, list):
        return jsonify({"error": "metas debe ser una lista"}), 400

    metas_limpias = [
        {
            "descripcion": str(m.get("descripcion", ""))[:300],
            "cumplimiento": max(0, min(100, int(m.get("cumplimiento", 0) or 0))),
            "comentario": str(m.get("comentario", ""))[:300],
        }
        for m in metas[:20]
    ]
    result = mongo.db.evaluaciones.update_one({"_id": eid}, {"$set": {"metas": metas_limpias}})
    if result.matched_count == 0:
        return jsonify({"error": "Evaluación no encontrada"}), 404

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "update", "evaluaciones", evaluacion_id, detalle="metas actualizadas")

    return jsonify({"message": "Metas actualizadas"}), 200


def guardar_autoevaluacion(mongo, evaluacion_id, data, identity):
    try:
        eid = ObjectId(evaluacion_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    doc = mongo.db.evaluaciones.find_one({"_id": eid})
    if not doc:
        return jsonify({"error": "Evaluación no encontrada"}), 404

    own_empleado_id = identity.get("empleado_id") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    if role not in ("ADMIN", "SUPER_ADMIN") and str(doc["empleado_id"]) != str(own_empleado_id):
        return jsonify({"error": "Solo puedes llenar tu propia autoevaluación"}), 403

    criterios, puntaje_criterios = _procesar_criterios(data.get("criterios"))
    puntaje = puntaje_criterios
    if puntaje is None:
        try:
            puntaje = int(data.get("puntaje"))
            if not (1 <= puntaje <= 5):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Califica al menos un criterio o da un puntaje general de 1 a 5"}), 400

    autoeval = {
        "puntaje": puntaje,
        "criterios": criterios,
        "comentario": str(data.get("comentario", ""))[:1000],
        "completada": True,
        "completada_en": datetime.now(timezone.utc).isoformat(),
    }
    mongo.db.evaluaciones.update_one({"_id": eid}, {"$set": {"autoevaluacion": autoeval}})

    usuario = identity.get("user") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "update", "evaluaciones", evaluacion_id, detalle="autoevaluación completada")

    return jsonify({"message": "Autoevaluación guardada"}), 200


def guardar_evaluacion_jefe(mongo, evaluacion_id, data, identity):
    try:
        eid = ObjectId(evaluacion_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    if not mongo.db.evaluaciones.find_one({"_id": eid}):
        return jsonify({"error": "Evaluación no encontrada"}), 404

    criterios, puntaje_criterios = _procesar_criterios(data.get("criterios"))
    puntaje = puntaje_criterios
    if puntaje is None:
        try:
            puntaje = int(data.get("puntaje"))
            if not (1 <= puntaje <= 5):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Califica al menos un criterio o da un puntaje general de 1 a 5"}), 400

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None

    evaluacion_jefe = {
        "puntaje": puntaje,
        "criterios": criterios,
        "comentario": str(data.get("comentario", ""))[:1000],
        "completada": True,
        "completada_en": datetime.now(timezone.utc).isoformat(),
        "evaluador": usuario,
    }
    mongo.db.evaluaciones.update_one({"_id": eid}, {"$set": {"evaluacion_jefe": evaluacion_jefe}})
    registrar_auditoria(mongo, usuario, role, "update", "evaluaciones", evaluacion_id, detalle="evaluación de jefe completada")

    return jsonify({"message": "Evaluación de jefe guardada"}), 200
