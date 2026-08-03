# api/documentosfinancieros/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Documentos financieros del empleado: recibos de nómina (los sube el admin,
# el empleado solo consulta/descarga) y CFDI de prestadores de servicios (el
# propio prestador los sube para que le paguen; admin/contador los revisa y
# marca como pagados). El PDF viaja como base64, igual que RH/expediente
# clínico — sin filesystem, funciona igual en cualquier servidor.
# ─────────────────────────────────────────────────────────────────────────────
from flask import jsonify, Response
from bson.objectid import ObjectId
from bson.errors import InvalidId
import json
import logging

logger = logging.getLogger(__name__)

TIPOS_VALIDOS = ("nomina", "cfdi")
ESTADOS_VALIDOS = ("pendiente", "pagado")


def _serialize(doc):
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    doc["empleado_id"] = str(doc["empleado_id"])
    return doc


def create_documento(mongo, empleado_id, data, subido_por_role):
    try:
        tipo = data.get("tipo")
        if tipo not in TIPOS_VALIDOS:
            return jsonify({"error": f"tipo debe ser uno de {TIPOS_VALIDOS}"}), 400

        periodo = (data.get("periodo") or "").strip()
        if not periodo:
            return jsonify({"error": "periodo es requerido (ej. 2026-07)"}), 400

        archivo = data.get("archivo_pdf")
        if not archivo:
            return jsonify({"error": "archivo_pdf es requerido"}), 400

        payload = {
            "empleado_id":    ObjectId(empleado_id),
            "tipo":           tipo,
            "periodo":        periodo,
            "nombre_archivo": (data.get("nombre_archivo") or f"{tipo}-{periodo}.pdf")[:150],
            "archivo_pdf":    archivo,
            "monto":          str(data.get("monto") or "")[:50],
            "estado":         "pagado" if tipo == "nomina" else "pendiente",
            "subido_por":     subido_por_role,
        }
        from datetime import datetime, timezone
        payload["creado_en"] = datetime.now(timezone.utc).isoformat()

        result = mongo.db.documentosfinancieros.insert_one(payload)
        return jsonify({"_id": str(result.inserted_id), "message": "Documento guardado"}), 201
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400
    except Exception as e:
        logger.error(f"Error creando documento financiero: {e}")
        return jsonify({"error": str(e)}), 500


def get_documentos_by_empleado(mongo, empleado_id, incluir_pdf=True):
    try:
        eid = ObjectId(empleado_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "empleado_id inválido"}), 400

    try:
        proyeccion = None if incluir_pdf else {"archivo_pdf": 0}
        docs = list(mongo.db.documentosfinancieros.find({"empleado_id": eid}, proyeccion))
        docs.sort(key=lambda d: d.get("periodo", ""), reverse=True)
        # json.dumps (no jsonify) para no truncar el base64 del PDF.
        return Response(
            json.dumps([_serialize(d) for d in docs], default=str),
            mimetype="application/json",
        )
    except Exception as e:
        logger.error(f"Error listando documentos financieros: {e}")
        return jsonify({"error": str(e)}), 500


def update_estado(mongo, doc_id, estado):
    if estado not in ESTADOS_VALIDOS:
        return jsonify({"error": f"estado debe ser uno de {ESTADOS_VALIDOS}"}), 400
    try:
        result = mongo.db.documentosfinancieros.update_one(
            {"_id": ObjectId(doc_id)}, {"$set": {"estado": estado}}
        )
        if result.matched_count == 0:
            return jsonify({"error": "Documento no encontrado"}), 404
        return jsonify({"message": "Estado actualizado"}), 200
    except (InvalidId, Exception) as e:
        return jsonify({"error": str(e)}), 400


def delete_documento(mongo, doc_id):
    try:
        result = mongo.db.documentosfinancieros.delete_one({"_id": ObjectId(doc_id)})
        if result.deleted_count == 0:
            return jsonify({"error": "Documento no encontrado"}), 404
        return jsonify({"message": "Documento eliminado"}), 200
    except (InvalidId, Exception) as e:
        return jsonify({"error": str(e)}), 400


def get_doc_owner_info(mongo, doc_id):
    """
    Retorna {empleado_id, tipo, estado} del documento, o None si no existe.
    Se usa para permitir que un empleado borre su propio CFDI mientras siga
    "pendiente" (una vez pagado, queda como comprobante y ya no se borra).
    """
    try:
        doc = mongo.db.documentosfinancieros.find_one({"_id": ObjectId(doc_id)})
        if not doc:
            return None
        return {
            "empleado_id": str(doc["empleado_id"]),
            "tipo": doc.get("tipo"),
            "estado": doc.get("estado"),
        }
    except (InvalidId, Exception):
        return None
