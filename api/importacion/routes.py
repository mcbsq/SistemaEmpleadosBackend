# api/importacion/routes.py
#   GET  /importacion/plantilla  → descarga la plantilla .xlsx (con las áreas de la empresa)
#   POST /importacion/validar    → {archivo, crear_cuentas} → vista previa por fila, sin guardar
#   POST /importacion/confirmar  → mismo cuerpo → guarda las filas sin errores
# Solo SUPER_ADMIN y RH: ADMIN está limitado a sus áreas y una carga masiva
# de toda la empresa no encaja con esa restricción.
import logging

from flask import Response, jsonify, request
from flask_jwt_extended import get_jwt

from api.auth_decorators import require_roles
from api.usuario.logic import create_usuario, usuario_existente
from core.audit import registrar_auditoria
from .logic import ArchivoInvalido, importar, leer, publico, validar
from .plantilla import generar_plantilla

logger = logging.getLogger(__name__)
ROLES_IMPORTACION = ("SUPER_ADMIN", "RH")


def _resumen_validacion(filas):
    return {
        "total": len(filas),
        "crear": sum(1 for f in filas if f["accion"] == "crear" and f["estado"] != "error"),
        "actualizar": sum(1 for f in filas if f["accion"] == "actualizar" and f["estado"] != "error"),
        "con_errores": sum(1 for f in filas if f["estado"] == "error"),
        "con_avisos": sum(1 for f in filas if f["estado"] == "aviso"),
    }


def setup_importacion_routes(app, mongo):

    @app.route('/importacion/plantilla', methods=['GET'])
    @require_roles(*ROLES_IMPORTACION)
    def plantilla_route():
        areas = [a.get("NombreDepto") for a in mongo.db.catalogodepto.find({}, {"NombreDepto": 1})]
        contenido = generar_plantilla(areas)
        return Response(contenido, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="plantilla-carga-empleados.xlsx"'})

    def _leer_y_validar():
        data = request.get_json(silent=True) or {}
        crear_cuentas = bool(data.get("crear_cuentas"))
        filas = leer(data.get("archivo") or "")
        return validar(mongo, filas, crear_cuentas=crear_cuentas), crear_cuentas

    @app.route('/importacion/validar', methods=['POST'])
    @require_roles(*ROLES_IMPORTACION)
    def validar_route():
        try:
            validadas, _ = _leer_y_validar()
        except ArchivoInvalido as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"resumen": _resumen_validacion(validadas), "filas": publico(validadas)}), 200

    @app.route('/importacion/confirmar', methods=['POST'])
    @require_roles(*ROLES_IMPORTACION)
    def confirmar_route():
        identity = get_jwt()
        try:
            validadas, crear_cuentas = _leer_y_validar()
        except ArchivoInvalido as e:
            return jsonify({"error": str(e)}), 400

        def crear_cuenta(l, empleado_id):
            usuario = l["CorreoTrabajo"].split("@", 1)[0]
            nombre = f"{l['Nombre']} {l['ApelPaterno']}".strip()
            if usuario_existente(mongo, usuario, l["CorreoTrabajo"]):
                return {"ok": False, "nombre": nombre, "error": "Ya existe una cuenta con ese usuario o correo."}
            try:
                resp = create_usuario(mongo, usuario, None, empleado_id, "EMPLOYEE", email=l["CorreoTrabajo"])
                cuerpo, status = (resp if isinstance(resp, tuple) else (resp, resp.status_code))
                datos = cuerpo.get_json() or {}
            except Exception as e:      # una cuenta fallida no detiene la importación
                logger.error(f"Error creando cuenta en importación: {e}")
                return {"ok": False, "nombre": nombre, "error": "No se pudo crear la cuenta."}
            if status >= 300:
                return {"ok": False, "nombre": nombre, "error": datos.get("error") or "No se pudo crear la cuenta."}
            return {"ok": True, "nombre": nombre, "usuario": usuario, "email": l["CorreoTrabajo"],
                    "temp_password": datos.get("temp_password"), "email_enviado": bool(datos.get("email_sent"))}

        resumen = importar(mongo, validadas, crear_cuenta_fn=crear_cuenta if crear_cuentas else None)
        registrar_auditoria(mongo, identity.get("user"), identity.get("role"), "create", "importacion_masiva", "",
                            detalle=f"creados={resumen['creados']} actualizados={resumen['actualizados']} "
                                    f"omitidos={resumen['omitidos']} cuentas={len(resumen['cuentas'])}")
        return jsonify({**resumen, "filas_con_error": [f for f in publico(validadas) if f["estado"] == "error"]}), 200
