# api/analitica/logic.py
# ─────────────────────────────────────────────────────────────────────────────
# Permite a un SUPER_ADMIN decidir qué reportes puede VER/EXPORTAR cada rol,
# sin necesidad de darle acceso al módulo completo (ej. CONTADOR puede ver
# "Resumen de nómina" sin volverse ADMIN). ADMIN/SUPER_ADMIN siempre ven todo.
from flask import jsonify, send_file

from core.audit import registrar_auditoria
from core.reportes import CATALOGO_REPORTES, GENERADORES

ROLES_TODOS = ("EMPLOYEE", "JEFE_AREA", "CONTADOR", "PROJECT_MANAGER", "MEDICO")


def get_permisos(mongo):
    doc = mongo.db.analitica_permisos.find_one({"tipo": "config"})
    return (doc or {}).get("permisos", {})


def catalogo_para_rol(mongo, role):
    permisos = get_permisos(mongo)
    otorgados = set(permisos.get(role, []))
    siempre_todo = role in ("ADMIN", "SUPER_ADMIN")
    return [
        {**r, "permitido": siempre_todo or r["id"] in otorgados}
        for r in CATALOGO_REPORTES
    ]


def get_catalogo_route(mongo, identity):
    role = identity.get("role") if isinstance(identity, dict) else None
    return jsonify(catalogo_para_rol(mongo, role)), 200


def get_permisos_route(mongo):
    permisos = get_permisos(mongo)
    return jsonify({"permisos": {r: permisos.get(r, []) for r in ROLES_TODOS}}), 200


def guardar_permisos(mongo, data, identity):
    permisos = data.get("permisos")
    if not isinstance(permisos, dict):
        return jsonify({"error": "permisos debe ser un objeto {rol: [ids]}"}), 400

    ids_validos = {r["id"] for r in CATALOGO_REPORTES}
    limpio = {}
    for role, ids in permisos.items():
        if role not in ROLES_TODOS or not isinstance(ids, list):
            continue
        limpio[role] = [i for i in ids if i in ids_validos]

    antes = get_permisos(mongo)
    mongo.db.analitica_permisos.update_one(
        {"tipo": "config"}, {"$set": {"tipo": "config", "permisos": limpio}}, upsert=True,
    )

    usuario = identity.get("user") if isinstance(identity, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "update", "analitica_permisos", None,
                         cambios={"permisos": {"antes": antes, "despues": limpio}})

    return jsonify({"message": "Permisos de analítica actualizados"}), 200


def _puede(role, permisos, reporte_id):
    return role in ("ADMIN", "SUPER_ADMIN") or reporte_id in permisos.get(role, [])


def resumen_sistema(mongo, identity):
    role = identity.get("role") if isinstance(identity, dict) else None
    permisos = get_permisos(mongo)
    es_admin = role in ("ADMIN", "SUPER_ADMIN")
    resumen = {}

    if _puede(role, permisos, "headcount"):
        pipeline = [
            {"$match": {"estado": {"$ne": "pendiente"}}},
            {"$group": {"_id": {"$ifNull": ["$depto_id", "Sin asignar"]}, "total": {"$sum": 1}}},
            {"$sort": {"total": -1}},
        ]
        por_depto = [{"label": r["_id"], "value": r["total"]} for r in mongo.db.empleados.aggregate(pipeline)]
        resumen["headcount"] = {
            "total": sum(r["value"] for r in por_depto),
            "por_departamento": por_depto,
        }

    if _puede(role, permisos, "nomina_resumen"):
        from api.nomina.logic import calcular_nomina_dict
        netos = []
        for rh in mongo.db.rh.find({"TipoRelacionLaboral": {"$ne": "prestador_servicios"}}):
            calc = calcular_nomina_dict(mongo, str(rh["empleado_id"]))
            if calc:
                netos.append(calc["neto"])
        resumen["nomina"] = {
            "empleados_en_nomina": len(netos),
            "masa_salarial_neta": round(sum(netos), 2),
            "promedio_neto": round(sum(netos) / len(netos), 2) if netos else 0,
        }

    if _puede(role, permisos, "vacaciones_uso"):
        from datetime import date
        inicio_anio = f"{date.today().year}-01-01"
        aprobadas = pendientes = 0
        dias_aprobados = 0
        for sol in mongo.db.vacaciones_solicitudes.find({"fecha_inicio": {"$gte": inicio_anio}}):
            if sol.get("estado") == "aprobada":
                aprobadas += 1
                dias_aprobados += sol.get("dias_solicitados", 0)
            elif sol.get("estado") == "pendiente":
                pendientes += 1
        resumen["vacaciones"] = {
            "solicitudes_aprobadas": aprobadas,
            "dias_aprobados_anio": dias_aprobados,
            "solicitudes_pendientes": pendientes,
        }

    if _puede(role, permisos, "desempeno_resumen"):
        ciclo = mongo.db.ciclos_evaluacion.find_one(sort=[("creado_en", -1)])
        if ciclo:
            autoevals, jefeevals = [], []
            for ev in mongo.db.evaluaciones.find({"ciclo_id": ciclo["_id"]}):
                if ev.get("autoevaluacion", {}).get("completada"):
                    autoevals.append(ev["autoevaluacion"]["puntaje"])
                if ev.get("evaluacion_jefe", {}).get("completada"):
                    jefeevals.append(ev["evaluacion_jefe"]["puntaje"])
            total_evs = mongo.db.evaluaciones.count_documents({"ciclo_id": ciclo["_id"]})
            resumen["desempeno"] = {
                "ciclo": ciclo["nombre"],
                "promedio_autoevaluacion": round(sum(autoevals) / len(autoevals), 2) if autoevals else None,
                "promedio_jefe": round(sum(jefeevals) / len(jefeevals), 2) if jefeevals else None,
                "completadas": len(autoevals), "total": total_evs,
            }

    if es_admin:
        vacantes_abiertas = mongo.db.vacantes.count_documents({"estado": "abierta"})
        candidatos_total = mongo.db.candidatos.count_documents({})
        pipeline_etapas = mongo.db.candidatos.aggregate([
            {"$group": {"_id": "$etapa", "total": {"$sum": 1}}},
        ])
        por_etapa = {r["_id"]: r["total"] for r in pipeline_etapas}
        resumen["reclutamiento"] = {
            "vacantes_abiertas": vacantes_abiertas,
            "candidatos_total": candidatos_total,
            "por_etapa": por_etapa,
        }

    return jsonify(resumen), 200


def exportar_reporte(mongo, reporte_id, identity):
    role = identity.get("role") if isinstance(identity, dict) else None
    if role not in ("ADMIN", "SUPER_ADMIN"):
        permisos = get_permisos(mongo)
        if reporte_id not in permisos.get(role, []):
            return jsonify({"error": "No tienes permiso para exportar este reporte"}), 403

    generador = GENERADORES.get(reporte_id)
    if not generador:
        return jsonify({"error": "Reporte no encontrado"}), 404

    buf = generador(mongo)

    usuario = identity.get("user") if isinstance(identity, dict) else None
    registrar_auditoria(mongo, usuario, role, "export", "analitica", reporte_id)

    return send_file(
        buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=f"{reporte_id}.xlsx",
    )
