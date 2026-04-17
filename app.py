from flask import Flask, jsonify, request
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask_cors import CORS, cross_origin
import logging
import sys
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# CORS — opciones explícitas para cubrir preflight (OPTIONS) en todas las rutas
CORS(app,
     resources={r"/*": {"origins": "*"}},
     methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=False)

# Responder OPTIONS globalmente antes de que llegue a las rutas protegidas
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers["Access-Control-Allow-Origin"]  = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

app.config['JWT_SECRET_KEY'] = 'cibercom'
app.config['UPLOAD_FOLDER']  = r'C:\Users\luis1\Desktop\python-mongodb-restapi\src\api\expedienteclinico_pdf'

jwt = JWTManager(app)

MONGO_URI = 'mongodb+srv://cibercom:proyectos2022@cluster0.ilngp.mongodb.net/controlempleados?retryWrites=true&w=majority'

class MongoWrapper:
    def __init__(self, uri, db_name):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.db     = self.client[db_name]

try:
    logger.debug("Conectando a MongoDB Atlas...")
    mongo = MongoWrapper(MONGO_URI, "controlempleados")
    mongo.db.command('ping')
    logger.info("--- CONEXIÓN EXITOSA A MONGODB ATLAS ---")
except Exception as e:
    logger.error(f"ERROR CRÍTICO: No se pudo conectar a MongoDB: {str(e)}")
    sys.exit(1)

def create_super_admin():
    try:
        if not mongo.db.usuario.find_one({'role': 'SUPER_ADMIN'}):
            mongo.db.usuario.insert_one({
                'user':        'admin',
                'password':    generate_password_hash('admin123'),
                'role':        'SUPER_ADMIN',
                'empleado_id': None,
                'org_id':      'default',
            })
            logger.info("Super Admin creado.")
    except Exception as e:
        logger.error(f"Error al verificar Super Admin: {str(e)}")

create_super_admin()

# ─── Rutas ────────────────────────────────────────────────────────────────────
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
# from api.org.routes                 import setup_org_routes

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
# setup_org_routes(app, mongo)

@app.errorhandler(404)
def not_found(error=None):
    return jsonify({'message': 'Ruta no encontrada: ' + request.url, 'status': 404}), 404

@app.errorhandler(500)
def server_error(error=None):
    return jsonify({'message': 'Error interno del servidor', 'status': 500}), 500

if __name__ == "__main__":
    logger.info("Servidor Flask en puerto 5001.")
    app.run(debug=True, host='0.0.0.0', port=5001)