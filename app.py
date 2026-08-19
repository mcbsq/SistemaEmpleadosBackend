import os
import sys
import secrets
import logging

try:
    # Carga opcional de .env.local para desarrollo local. En producción,
    # define las variables directamente en el entorno del proceso/host y
    # esto simplemente no hace nada si el paquete no está instalado.
    from dotenv import load_dotenv
    load_dotenv(".env.local")
except ImportError:
    pass

from flask import Flask, jsonify, request, g
from pymongo import MongoClient
from flask_cors import CORS
from flask_jwt_extended import JWTManager, verify_jwt_in_request, get_jwt
from werkzeug.security import generate_password_hash

from core.tenant_db import BaseDatosMultiTenant

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# CORS — TODO (Fase D, ver docs/AEGIS...): restringir "origins" al dominio real
# del frontend antes de producción. "*" combinado con rutas sin @jwt_required()
# es la brecha más grande que tiene el proyecto hoy.
CORS_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
CORS(app,
     resources={r"/*": {"origins": CORS_ORIGINS}},
     methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=False)


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers["Access-Control-Allow-Origin"] = CORS_ORIGINS
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response


@app.before_request
def cargar_org_id():
    """
    Aislamiento multi-tenant: toda request con un JWT válido trae su org_id
    (el tenant resuelto en el login, ver api/login/logic.py) — se guarda en
    flask.g para que core/tenant_db.py filtre automáticamente cada consulta
    a Mongo por esa empresa. Rutas sin JWT (login, health) simplemente no
    tienen org_id todavía; el propio flujo de login lo fija a mano una vez
    que resuelve el tenant contra Aegis (ver _issue_token_response).
    Nunca lanza: un token ausente o inválido aquí no debe tumbar la request,
    eso ya lo decide el @jwt_required() de la ruta específica.
    """
    g.org_id = None
    try:
        verify_jwt_in_request(optional=True)
        claims = get_jwt()
        if claims:
            g.org_id = claims.get("org_id")
    except Exception:
        pass


# ─── Configuración obligatoria por variable de entorno ─────────────────────
# Sin default: si falta, el arranque falla explícito en vez de usar un
# secreto débil o una credencial real hardcodeada en el repo.
try:
    app.config['JWT_SECRET_KEY'] = os.environ['JWT_SECRET_KEY']
except KeyError:
    logger.error("Falta JWT_SECRET_KEY en el entorno. Genera uno con "
                 "secrets.token_urlsafe(64) y defínelo antes de arrancar.")
    sys.exit(1)

app.config['UPLOAD_FOLDER'] = os.environ.get(
    'UPLOAD_FOLDER',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api', 'expedienteclinico_pdf'),
)

# Duración del access token — el sistema está pensado para sesiones largas
# (un admin puede estar horas dentro de un expediente), así que se fija
# explícito en 15 minutos en vez de depender del default de la librería
# (que también son 15, pero sin esto no queda documentado ni es obvio dónde
# tocar si algún día hay que ajustarlo).
from datetime import timedelta
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=int(os.environ.get('JWT_ACCESS_MINUTES', 15)))

jwt = JWTManager(app)

try:
    MONGO_URI = os.environ['MONGO_URI']
except KeyError:
    logger.error("Falta MONGO_URI en el entorno. No hay valor por defecto por seguridad "
                 "(el anterior tenía la contraseña real de Atlas hardcodeada).")
    sys.exit(1)


class MongoWrapper:
    def __init__(self, uri, db_name):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.db = self.client[db_name]


try:
    logger.debug("Conectando a MongoDB Atlas...")
    mongo = MongoWrapper(MONGO_URI, "controlempleados")
    mongo.db.command('ping')
    logger.info("--- CONEXIÓN EXITOSA A MONGODB ATLAS ---")
except Exception as e:
    logger.error(f"ERROR CRÍTICO: No se pudo conectar a MongoDB: {str(e)}")
    sys.exit(1)

# Multi-tenencia real: a partir de aquí, mongo.db.<coleccion> filtra/etiqueta
# automáticamente por org_id (ver core/tenant_db.py). mongo.db.raw da acceso
# directo sin aislar, solo para los pocos casos que deliberadamente cruzan
# tenants (validar API keys por hash, el script de migración).
mongo.db = BaseDatosMultiTenant(mongo.db)


def create_super_admin():
    """
    Crea un SUPER_ADMIN solo si no existe ninguno y no se está usando Aegis
    para login. La contraseña NUNCA es un valor fijo en código: viene de
    SUPER_ADMIN_INITIAL_PASSWORD o se genera al vuelo y se imprime UNA sola
    vez para que el operador la cambie de inmediato.
    """
    try:
        from core.aegis_config import get_aegis_settings
        if get_aegis_settings()["login_enabled"]:
            logger.info(
                "Login Aegis activo: omitir creación automática de super_admin en Mongo; "
                "aprovisionar en Aegis y enlazar con aegis_user_id + role SUPER_ADMIN."
            )
            return

        if mongo.db.usuario.find_one({'role': 'SUPER_ADMIN'}):
            return

        env_password = os.environ.get('SUPER_ADMIN_INITIAL_PASSWORD')
        initial_password = env_password or secrets.token_urlsafe(12)

        mongo.db.usuario.insert_one({
            'user': 'admin',
            'password': generate_password_hash(initial_password),
            'role': 'SUPER_ADMIN',
            'empleado_id': None,
            'org_id': 'cibercom',
        })

        if env_password:
            logger.info("Super Admin creado con la contraseña de SUPER_ADMIN_INITIAL_PASSWORD.")
        else:
            logger.warning(
                "Super Admin creado con contraseña generada automáticamente: %s "
                "— cámbiala de inmediato. Este mensaje solo aparece una vez.",
                initial_password,
            )
    except Exception as e:
        logger.error(f"Error al verificar Super Admin: {str(e)}")


create_super_admin()

# ─── Rutas ───────────────────────────────────────────────────────────────────
from api.login.routes                 import setup_login_routes
from api.usuario.routes               import setup_usuario_routes
from api.empleados.routes             import setup_empleados_routes
from api.catalogodepto.routes         import setup_catalogodepto_routes
from api.comportamientolaboral.routes import setup_comportamientolaboral_routes
from api.datoscontacto.routes         import setup_datoscontacto_routes
from api.direccion.routes             import setup_direccion_routes
from api.educacion.routes             import setup_educacion_routes
from api.expedienteclinico.routes     import setup_expedienteclinico_routes
from api.personascontacto.routes      import setup_personascontacto_routes
from api.prestamo.routes              import setup_prestamo_routes
from api.redsocial.routes             import setup_redsocial_routes
from api.rh.routes                    import setup_rh_routes
from api.jerarquia.routes             import setup_jerarquia_routes
from api.roles.routes                 import setup_roles_routes
from api.monitor.routes               import setup_monitor_routes
from api.documentosfinancieros.routes import setup_documentosfinancieros_routes
from api.org.routes                   import setup_org_routes
from api.vacaciones.routes             import setup_vacaciones_routes
from api.apikeys.routes                import setup_apikeys_routes
from api.v1externo.routes              import setup_v1_externo_routes
from api.notificaciones.routes         import setup_notificaciones_routes
from api.auditoria.routes              import setup_auditoria_routes
from api.nomina.routes                 import setup_nomina_routes
from api.reclutamiento.routes          import setup_reclutamiento_routes
from api.desempeno.routes              import setup_desempeno_routes
from api.analitica.routes              import setup_analitica_routes
from api.catalogos.catalogos          import setup_catalogos_routes
from api.conexiones_externas.routes    import setup_conexiones_externas_routes
from api.tenants.routes                import setup_tenants_routes

setup_login_routes(app, mongo)
setup_usuario_routes(app, mongo)
setup_empleados_routes(app, mongo)
setup_catalogodepto_routes(app, mongo)
setup_comportamientolaboral_routes(app, mongo)
setup_datoscontacto_routes(app, mongo)
setup_direccion_routes(app, mongo)
setup_educacion_routes(app, mongo)
setup_expedienteclinico_routes(app, mongo)
setup_personascontacto_routes(app, mongo)
setup_prestamo_routes(app, mongo)
setup_redsocial_routes(app, mongo)
setup_rh_routes(app, mongo)
setup_jerarquia_routes(app, mongo)
setup_roles_routes(app, mongo)
setup_monitor_routes(app, mongo)
setup_documentosfinancieros_routes(app, mongo)
setup_org_routes(app, mongo)
setup_vacaciones_routes(app, mongo)
setup_apikeys_routes(app, mongo)
setup_v1_externo_routes(app, mongo)
setup_notificaciones_routes(app, mongo)
setup_auditoria_routes(app, mongo)
setup_nomina_routes(app, mongo)
setup_reclutamiento_routes(app, mongo)
setup_desempeno_routes(app, mongo)
setup_analitica_routes(app, mongo)
setup_catalogos_routes(app)
setup_conexiones_externas_routes(app, mongo)
setup_tenants_routes(app, mongo)


@app.errorhandler(404)
def not_found(error=None):
    return jsonify({'message': 'Ruta no encontrada: ' + request.url, 'status': 404}), 404


@app.errorhandler(500)
def server_error(error=None):
    return jsonify({'message': 'Error interno del servidor', 'status': 500}), 500


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Servidor Flask en puerto 5001 (debug=%s).", debug_mode)
    app.run(debug=debug_mode, host='0.0.0.0', port=5001)