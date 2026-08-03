# core/reportes.py
# ─────────────────────────────────────────────────────────────────────────────
# Generación de reportes .xlsx — la analítica que antes solo vivía en
# pantalla (KPIs del AdminDashboard) ahora se puede exportar y, con permisos,
# compartir con otros roles sin darles acceso a los módulos completos.
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font

from api.nomina.logic import calcular_nomina_dict

# Catálogo de reportes — id estable (se usa en analitica_permisos), nombre y
# descripción para la UI. Agregar un reporte nuevo aquí lo hace disponible
# automáticamente para asignar permisos por rol.
CATALOGO_REPORTES = [
    {"id": "headcount", "nombre": "Headcount por departamento", "descripcion": "Total de empleados activos agrupados por área."},
    {"id": "nomina_resumen", "nombre": "Resumen de nómina", "descripcion": "Percepciones, ISR, IMSS y neto de cada empleado en nómina.", "sensible": True},
    {"id": "vacaciones_uso", "nombre": "Uso de vacaciones", "descripcion": "Días solicitados y aprobados por empleado en el año en curso."},
    {"id": "desempeno_resumen", "nombre": "Resumen de desempeño", "descripcion": "Puntajes de autoevaluación y evaluación de jefe del ciclo más reciente."},
]


def _autoajustar_columnas(ws):
    for col in ws.columns:
        max_len = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 45)


def _nueva_hoja(titulo, encabezados):
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    ws.append(encabezados)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    return wb, ws


def _wb_a_bytes(wb, ws):
    _autoajustar_columnas(ws)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def reporte_headcount(mongo):
    wb, ws = _nueva_hoja("Headcount", ["Departamento", "Total empleados"])
    pipeline = [
        {"$match": {"estado": {"$ne": "pendiente"}}},
        {"$group": {"_id": {"$ifNull": ["$depto_id", "Sin asignar"]}, "total": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]
    for row in mongo.db.empleados.aggregate(pipeline):
        ws.append([row["_id"], row["total"]])
    return _wb_a_bytes(wb, ws)


def reporte_nomina_resumen(mongo):
    wb, ws = _nueva_hoja("Nomina", ["Empleado", "Percepción bruta", "ISR", "IMSS", "Neto mensual"])
    empleados = {str(e["_id"]): f"{e.get('Nombre','')} {e.get('ApelPaterno','')}".strip() for e in mongo.db.empleados.find()}
    for rh in mongo.db.rh.find({"TipoRelacionLaboral": {"$ne": "prestador_servicios"}}):
        eid = str(rh["empleado_id"])
        calc = calcular_nomina_dict(mongo, eid)
        if calc:
            ws.append([empleados.get(eid, eid), calc["percepcion_bruta"], calc["isr"], calc["imss"], calc["neto"]])
    return _wb_a_bytes(wb, ws)


def reporte_vacaciones_uso(mongo):
    wb, ws = _nueva_hoja("Vacaciones", ["Empleado", "Solicitudes", "Días aprobados", "Días pendientes", "Días rechazados"])
    empleados = {str(e["_id"]): f"{e.get('Nombre','')} {e.get('ApelPaterno','')}".strip() for e in mongo.db.empleados.find()}
    resumen = {}
    for sol in mongo.db.vacaciones_solicitudes.find():
        eid = str(sol["empleado_id"])
        r = resumen.setdefault(eid, {"solicitudes": 0, "aprobados": 0, "pendientes": 0, "rechazados": 0})
        r["solicitudes"] += 1
        dias = sol.get("dias_solicitados", 0)
        if sol.get("estado") == "aprobada":
            r["aprobados"] += dias
        elif sol.get("estado") == "pendiente":
            r["pendientes"] += dias
        else:
            r["rechazados"] += dias
    for eid, r in resumen.items():
        ws.append([empleados.get(eid, eid), r["solicitudes"], r["aprobados"], r["pendientes"], r["rechazados"]])
    return _wb_a_bytes(wb, ws)


def reporte_desempeno_resumen(mongo):
    wb, ws = _nueva_hoja("Desempeno", ["Ciclo", "Empleado", "Autoevaluación", "Evaluación de jefe"])
    ciclo = mongo.db.ciclos_evaluacion.find_one(sort=[("creado_en", -1)])
    if not ciclo:
        return _wb_a_bytes(wb, ws)
    empleados = {str(e["_id"]): f"{e.get('Nombre','')} {e.get('ApelPaterno','')}".strip() for e in mongo.db.empleados.find()}
    for ev in mongo.db.evaluaciones.find({"ciclo_id": ciclo["_id"]}):
        eid = str(ev["empleado_id"])
        auto = ev.get("autoevaluacion", {})
        jefe = ev.get("evaluacion_jefe", {})
        ws.append([
            ciclo["nombre"], empleados.get(eid, eid),
            auto.get("puntaje") if auto.get("completada") else "—",
            jefe.get("puntaje") if jefe.get("completada") else "—",
        ])
    return _wb_a_bytes(wb, ws)


GENERADORES = {
    "headcount": reporte_headcount,
    "nomina_resumen": reporte_nomina_resumen,
    "vacaciones_uso": reporte_vacaciones_uso,
    "desempeno_resumen": reporte_desempeno_resumen,
}
