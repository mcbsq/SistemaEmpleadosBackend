# api/panel_rh/routes.py
# ─────────────────────────────────────────────────────────────────────────────
# GET /rh/panel — el tablero del día de Recursos Humanos: qué hay que atender
# (solicitudes, vacaciones por aprobar), qué expedientes están incompletos
# (sin los datos que nómina e IMSS necesitan) y qué pasa esta semana
# (quién está de vacaciones, cumpleaños, aniversarios). Todo calculado aquí en
# una sola llamada para que el panel cargue de un golpe.
# ─────────────────────────────────────────────────────────────────────────────
from datetime import date, datetime, timedelta

from flask import jsonify

from api.auth_decorators import require_roles
from core.visibilidad_perfil import ROLES_RH

# Lo mínimo que RH necesita de cada persona para pagarle y darla de alta en el
# IMSS. Cada falta se reporta con el nombre que entiende RH, no el del campo.
CAMPOS_EXPEDIENTE = (
    ("Puesto", "puesto"), ("FechaIngreso", "fecha de ingreso"), ("CURP", "CURP"),
    ("RFC", "RFC"), ("NSS", "NSS"), ("SalarioDiario", "salario"), ("CLABE", "cuenta bancaria"),
)


def _fecha(valor):
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _proximo(fecha, hoy):
    """Siguiente aniversario (mismo día/mes) de `fecha` a partir de hoy."""
    try:
        f = fecha.replace(year=hoy.year)
    except ValueError:            # 29 de febrero en año no bisiesto
        f = date(hoy.year, 3, 1)
    if f < hoy:
        try:
            f = fecha.replace(year=hoy.year + 1)
        except ValueError:
            f = date(hoy.year + 1, 3, 1)
    return f


def setup_panel_rh_routes(app, mongo):

    @app.route('/rh/panel', methods=['GET'])
    @require_roles(*ROLES_RH)
    def panel_rh_route():
        hoy = date.today()
        fin_semana = hoy + timedelta(days=7)
        inicio_mes = hoy.replace(day=1)

        # Las cuentas administrativas (Administrador general / de área) no son
        # plantilla: no cuentan en KPIs ni en expedientes por completar.
        administrativos = {str(u.get("empleado_id")) for u in mongo.db.usuario.find(
            {"role": {"$in": ["SUPER_ADMIN", "ADMIN"]}}, {"empleado_id": 1}) if u.get("empleado_id")}
        empleados = [e for e in mongo.db.empleados.find({}, {
            "Nombre": 1, "ApelPaterno": 1, "estado": 1, "FecNacimiento": 1, "Fotografias": 1,
        }) if (e.get("estado") or "activo") not in ("pendiente", "baja") and str(e["_id"]) not in administrativos]
        activos = [e for e in empleados if (e.get("estado") or "activo") != "inactivo"]
        nombre = {str(e["_id"]): f"{e.get('Nombre', '')} {e.get('ApelPaterno', '')}".strip() for e in empleados}
        rh = {str(d.get("empleado_id")): d for d in mongo.db.rh.find({}, {"ExpedienteDigitalPDF": 0})}
        con_emergencia = {str(d.get("empleadoid")) for d in mongo.db.personascontacto.find({}, {"empleadoid": 1, "Contactos": 1}) if d.get("Contactos")}

        # Expedientes incompletos (solo personas activas), los más incompletos primero.
        incompletos = []
        for e in activos:
            eid = str(e["_id"])
            r = rh.get(eid, {})
            faltan = [label for campo, label in CAMPOS_EXPEDIENTE if not str(r.get(campo) or "").strip()]
            if eid not in con_emergencia:
                faltan.append("contacto de emergencia")
            if faltan:
                incompletos.append({"empleado_id": eid, "nombre": nombre[eid], "faltan": faltan})
        incompletos.sort(key=lambda x: -len(x["faltan"]))

        altas_mes = [eid for eid, r in rh.items() if eid in nombre and (_fecha(r.get("FechaIngreso")) or date.min) >= inicio_mes]

        # Vacaciones: por aprobar, y quién está fuera hoy / esta semana.
        vac_pendientes, fuera = [], []
        for v in mongo.db.vacaciones_solicitudes.find({"estado": {"$in": ["pendiente", "aprobada"]}}):
            eid = str(v.get("empleado_id"))
            if eid not in nombre:
                continue
            item = {"empleado_id": eid, "nombre": nombre[eid], "fecha_inicio": v.get("fecha_inicio"),
                    "fecha_fin": v.get("fecha_fin"), "dias": v.get("dias_solicitados")}
            if v.get("estado") == "pendiente":
                vac_pendientes.append(item)
            else:
                ini, fin = _fecha(v.get("fecha_inicio")), _fecha(v.get("fecha_fin"))
                if ini and fin and ini <= fin_semana and fin >= hoy:
                    fuera.append({**item, "hoy": ini <= hoy <= fin})
        fuera.sort(key=lambda x: (not x["hoy"], x["fecha_inicio"] or ""))

        # Esta semana: cumpleaños y aniversarios laborales.
        eventos = []
        for e in activos:
            eid = str(e["_id"])
            nac = _fecha(e.get("FecNacimiento"))
            if nac:
                prox = _proximo(nac, hoy)
                if prox <= fin_semana:
                    eventos.append({"empleado_id": eid, "nombre": nombre[eid], "tipo": "cumpleanos", "fecha": prox.isoformat()})
            ing = _fecha(rh.get(eid, {}).get("FechaIngreso"))
            if ing:
                prox = _proximo(ing, hoy)
                anios = prox.year - ing.year
                if anios >= 1 and prox <= fin_semana:
                    eventos.append({"empleado_id": eid, "nombre": nombre[eid], "tipo": "aniversario", "fecha": prox.isoformat(), "anios": anios})
        eventos.sort(key=lambda x: x["fecha"])

        solicitudes = list(mongo.db.solicitudes_rh.find({"estado": {"$in": ["abierta", "en_proceso"]}}).sort("creado_en", -1))

        return jsonify({
            "kpis": {
                "plantilla": len(activos),
                "inactivos": len(empleados) - len(activos),
                "altas_mes": len(altas_mes),
                "solicitudes_pendientes": len(solicitudes),
                "vacaciones_por_aprobar": len(vac_pendientes),
                "fuera_hoy": sum(1 for f in fuera if f["hoy"]),
                "expedientes_incompletos": len(incompletos),
                "expedientes_completos_pct": round(100 * (len(activos) - len(incompletos)) / len(activos)) if activos else 100,
            },
            "solicitudes": [{
                "_id": str(s["_id"]), "empleado_id": s.get("empleado_id"), "nombre": s.get("empleado_nombre", ""),
                "asunto": s.get("asunto", ""), "estado": s.get("estado"), "creado_en": s.get("creado_en"),
            } for s in solicitudes[:50]],
            "vacaciones_por_aprobar": vac_pendientes[:50],
            "fuera": fuera[:50],
            "eventos": eventos[:50],
            "incompletos": incompletos[:300],
        }), 200
