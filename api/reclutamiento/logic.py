# api/reclutamiento/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Reclutamiento: vacantes + candidatos con pipeline por etapas, patrón usado
# por sistemas de mercado (Greenhouse/BambooHR) simplificado — sin
# integraciones de bolsas de trabajo externas, solo el flujo interno.
from datetime import datetime, timezone
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask import jsonify
import logging

from core.audit import registrar_auditoria

logger = logging.getLogger(__name__)

ETAPAS_VALIDAS = ("aplicado", "entrevista", "oferta", "contratado", "rechazado")

# Criterios estándar de evaluación de candidatos — el mismo set que usan
# scorecards de mercado (Greenhouse/LinkedIn Talent) para comparar candidatos
# de forma objetiva en vez de una sola impresión general. 1-5 cada uno.
CRITERIOS_RECLUTAMIENTO = [
    {"id": "conocimiento_tecnico", "nombre": "Conocimiento técnico"},
    {"id": "experiencia",          "nombre": "Experiencia relevante"},
    {"id": "comunicacion",         "nombre": "Comunicación"},
    {"id": "resolucion_problemas", "nombre": "Resolución de problemas"},
    {"id": "fit_cultural",         "nombre": "Fit cultural"},
    {"id": "referencias",          "nombre": "Referencias"},
]
_IDS_CRITERIOS_RECLUT = {c["id"] for c in CRITERIOS_RECLUTAMIENTO}


def _procesar_criterios_candidato(data_criterios):
    criterios = []
    if isinstance(data_criterios, list):
        for c in data_criterios:
            cid = c.get("id")
            if cid not in _IDS_CRITERIOS_RECLUT:
                continue
            try:
                p = int(c.get("puntaje"))
                if not (1 <= p <= 5):
                    continue
            except (TypeError, ValueError):
                continue
            criterios.append({"id": cid, "puntaje": p})
    puntaje_promedio = round(sum(c["puntaje"] for c in criterios) / len(criterios), 1) if criterios else None
    return criterios, puntaje_promedio


def _serializar_vacante(doc, conteo_candidatos=None):
    out = {
        "_id": str(doc["_id"]),
        "titulo": doc.get("titulo"),
        "departamento": doc.get("departamento"),
        "descripcion": doc.get("descripcion"),
        "requisitos": doc.get("requisitos"),
        "ubicacion": doc.get("ubicacion"),
        "tipo_contrato": doc.get("tipo_contrato"),
        "estado": doc.get("estado", "abierta"),
        "creado_por": doc.get("creado_por"),
        "creado_en": doc.get("creado_en"),
    }
    if conteo_candidatos is not None:
        out["candidatos_count"] = conteo_candidatos
    return out


def _serializar_candidato(doc):
    return {
        "_id": str(doc["_id"]),
        "vacante_id": str(doc["vacante_id"]),
        "nombre": doc.get("nombre"),
        "email": doc.get("email"),
        "telefono": doc.get("telefono"),
        "cv_pdf": bool(doc.get("cv_pdf")),
        "etapa": doc.get("etapa", "aplicado"),
        "notas": doc.get("notas", ""),
        "criterios": doc.get("criterios", []),
        "puntaje_promedio": doc.get("puntaje_promedio"),
        "creado_en": doc.get("creado_en"),
        "actualizado_en": doc.get("actualizado_en"),
    }


def listar_vacantes(mongo):
    docs = list(mongo.db.vacantes.find().sort("creado_en", -1))
    out = []
    for d in docs:
        count = mongo.db.candidatos.count_documents({"vacante_id": d["_id"]})
        out.append(_serializar_vacante(d, count))
    return jsonify(out), 200


def crear_vacante(mongo, data, identity):
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"error": "El título es requerido"}), 400

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None

    doc = {
        "titulo": titulo[:150],
        "departamento": (data.get("departamento") or "").strip()[:100],
        "descripcion": (data.get("descripcion") or "").strip()[:2000],
        "requisitos": (data.get("requisitos") or "").strip()[:2000],
        "ubicacion": (data.get("ubicacion") or "").strip()[:150],
        "tipo_contrato": (data.get("tipo_contrato") or "tiempo_completo").strip(),
        "estado": "abierta",
        "creado_por": usuario,
        "creado_en": datetime.now(timezone.utc).isoformat(),
    }
    result = mongo.db.vacantes.insert_one(doc)
    registrar_auditoria(mongo, usuario, role, "create", "vacantes", str(result.inserted_id), detalle=titulo)
    return jsonify(_serializar_vacante({**doc, "_id": result.inserted_id}, 0)), 201


def actualizar_vacante(mongo, vacante_id, data, identity):
    try:
        vid = ObjectId(vacante_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    campos = {}
    for campo in ("titulo", "departamento", "descripcion", "requisitos", "ubicacion", "tipo_contrato", "estado"):
        if campo in data:
            campos[campo] = data[campo]
    if "estado" in campos and campos["estado"] not in ("abierta", "cerrada"):
        return jsonify({"error": "estado debe ser abierta o cerrada"}), 400

    result = mongo.db.vacantes.update_one({"_id": vid}, {"$set": campos})
    if result.matched_count == 0:
        return jsonify({"error": "Vacante no encontrada"}), 404

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "update", "vacantes", vacante_id, cambios=campos)

    return jsonify({"message": "Vacante actualizada"}), 200


def eliminar_vacante(mongo, vacante_id, identity):
    try:
        vid = ObjectId(vacante_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    result = mongo.db.vacantes.delete_one({"_id": vid})
    if result.deleted_count == 0:
        return jsonify({"error": "Vacante no encontrada"}), 404
    mongo.db.candidatos.delete_many({"vacante_id": vid})

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "delete", "vacantes", vacante_id)

    return jsonify({"message": "Vacante y candidatos eliminados"}), 200


def listar_candidatos(mongo, vacante_id):
    try:
        vid = ObjectId(vacante_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    docs = list(mongo.db.candidatos.find({"vacante_id": vid}).sort("creado_en", -1))
    return jsonify([_serializar_candidato(d) for d in docs]), 200


def crear_candidato(mongo, vacante_id, data, identity):
    try:
        vid = ObjectId(vacante_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    if not mongo.db.vacantes.find_one({"_id": vid}):
        return jsonify({"error": "Vacante no encontrada"}), 404

    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400

    doc = {
        "vacante_id": vid,
        "nombre": nombre[:150],
        "email": (data.get("email") or "").strip()[:150],
        "telefono": (data.get("telefono") or "").strip()[:30],
        "cv_pdf": data.get("cv_pdf"),
        "etapa": "aplicado",
        "notas": (data.get("notas") or "").strip()[:1000],
        "criterios": [],
        "puntaje_promedio": None,
        "creado_en": datetime.now(timezone.utc).isoformat(),
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }
    result = mongo.db.candidatos.insert_one(doc)

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "create", "candidatos", str(result.inserted_id), detalle=nombre)

    return jsonify(_serializar_candidato({**doc, "_id": result.inserted_id})), 201


def actualizar_etapa_candidato(mongo, candidato_id, nueva_etapa, identity):
    if nueva_etapa not in ETAPAS_VALIDAS:
        return jsonify({"error": f"etapa debe ser una de {ETAPAS_VALIDAS}"}), 400
    try:
        cid = ObjectId(candidato_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400

    antes = mongo.db.candidatos.find_one({"_id": cid})
    if not antes:
        return jsonify({"error": "Candidato no encontrado"}), 404

    mongo.db.candidatos.update_one(
        {"_id": cid},
        {"$set": {"etapa": nueva_etapa, "actualizado_en": datetime.now(timezone.utc).isoformat()}},
    )

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(
        mongo, usuario, role, "update", "candidatos", candidato_id,
        cambios={"etapa": {"antes": antes.get("etapa"), "despues": nueva_etapa}},
    )

    return jsonify({"message": "Etapa actualizada"}), 200


def evaluar_candidato(mongo, candidato_id, data, identity):
    try:
        cid = ObjectId(candidato_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    if not mongo.db.candidatos.find_one({"_id": cid}):
        return jsonify({"error": "Candidato no encontrado"}), 404

    criterios, promedio = _procesar_criterios_candidato(data.get("criterios"))
    if not criterios:
        return jsonify({"error": "Califica al menos un criterio (1-5)"}), 400

    mongo.db.candidatos.update_one(
        {"_id": cid},
        {"$set": {
            "criterios": criterios,
            "puntaje_promedio": promedio,
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }},
    )

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "update", "candidatos", candidato_id, detalle="scorecard actualizado")

    return jsonify({"message": "Evaluación guardada", "puntaje_promedio": promedio}), 200


def eliminar_candidato(mongo, candidato_id, identity):
    try:
        cid = ObjectId(candidato_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "ID inválido"}), 400
    result = mongo.db.candidatos.delete_one({"_id": cid})
    if result.deleted_count == 0:
        return jsonify({"error": "Candidato no encontrado"}), 404

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "delete", "candidatos", candidato_id)

    return jsonify({"message": "Candidato eliminado"}), 200
