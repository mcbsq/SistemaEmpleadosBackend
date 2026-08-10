# api/v1externo/routes.py
# ─────────────────────────────────────────────────────────────────────────────
# Superficie de consumo EXTERNO del sistema: lo que otro programa puede leer
# usando una API key (ver core/apikey_auth.py y api/apikeys/). Solo lectura;
# nunca se expone aquí una ruta de escritura. Reutiliza la misma lógica que
# ya usan las rutas internas (get_empleados, get_rhs, obtener_jerarquia_logic)
# para no duplicar reglas de formato/redacción de datos sensibles.
from flask import jsonify

from core.apikey_auth import require_api_key
from api.empleados.logic import get_empleados
from api.rh.logic import get_rhs
from api.jerarquia.logic import obtener_jerarquia_logic


def setup_v1_externo_routes(app, mongo):

    def empleado_fiscal_sif(empleado):
        """Contrato mínimo para nómina CFID; solo datos necesarios para timbrar."""
        empleado_id = str(empleado["_id"])
        rh = mongo.db.rh.find_one({"empleado_id": empleado["_id"]}) or {}
        contacto = mongo.db.datoscontacto.find_one({"EmpleadoId": empleado["_id"]}) or {}
        usuario = mongo.db.usuario.find_one({"empleado_id": empleado_id}) or {}
        nombre = (empleado.get("Nombre") or "").strip()
        paterno = (empleado.get("ApelPaterno") or "").strip()
        materno = (empleado.get("ApelMaterno") or "").strip()
        completo = " ".join(part for part in (nombre, paterno, materno) if part)
        correo = contacto.get("ListaCorreos") or usuario.get("email") or ""
        if isinstance(correo, list):
            correo = next((str(x).strip() for x in correo if str(x).strip()), "")
        return {
            "idEmpleados": empleado_id,
            "noEmpleado": str(rh.get("NumeroEmpleado") or empleado_id),
            "estado": "activo",
            "nombre": nombre,
            "apellidoPaterno": paterno,
            "apellidoMaterno": materno,
            "nombreCompleto": completo,
            "rfc": str(rh.get("RFC") or "").strip().upper(),
            "curp": str(rh.get("CURP") or "").strip().upper(),
            "correoElectronico": str(correo).strip(),
            "telefono": str(contacto.get("TelCelular") or contacto.get("TelFijo") or "").strip(),
            "codigoPostal": "",
            "numSeguridadSocial": "",
            "salarioDiarioIntegrado": "",
            "salarioBase": str(rh.get("Salario") or "").strip(),
            "periodicidadPago": "QUINCENAL",
            "periodoPagoSat": "04",
            "fechaIngreso": str(rh.get("FechaIngreso") or "").strip(),
            "riesgoPuesto": "",
            "puesto": str(rh.get("Puesto") or empleado.get("Cargo") or "").strip(),
            "departamento": str(rh.get("Departamento") or empleado.get("depto_id") or "").strip(),
        }

    # Sin scope específico — cualquier API key activa la puede usar para
    # confirmar que la conexión y el header Authorization están bien armados
    # antes de tocar un recurso real. Pensado para pruebas de integración.
    @app.route('/api/v1/ping', methods=['GET'])
    @require_api_key(mongo)
    def v1_ping_route():
        return jsonify({"status": "ok", "message": "API key válida"}), 200

    @app.route('/api/v1/empleados', methods=['GET'])
    @require_api_key(mongo, 'empleados:read')
    def v1_get_empleados_route():
        return get_empleados(mongo)

    @app.route('/api/v1/empleados/fiscal-sif', methods=['GET'])
    @require_api_key(mongo, 'empleados:read')
    def v1_get_empleados_fiscal_sif_route():
        empleados = mongo.db.empleados.find({"estado": {"$ne": "pendiente"}})
        return jsonify({"empleados": [empleado_fiscal_sif(emp) for emp in empleados]}), 200

    @app.route('/api/v1/rh', methods=['GET'])
    @require_api_key(mongo, 'rh:read')
    def v1_get_rh_route():
        return get_rhs(mongo)

    @app.route('/api/v1/organigrama', methods=['GET'])
    @require_api_key(mongo, 'organigrama:read')
    def v1_get_jerarquia_route():
        return obtener_jerarquia_logic(mongo)
