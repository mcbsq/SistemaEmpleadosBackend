from flask import Flask, jsonify, request
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from flask_cors import CORS
import logging
import sys
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash

# 1. CONFIGURACIÓN DE LOGGING
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 2. INSTANCIA DE LA APP
app = Flask(__name__)

# 3. CONFIGURACIÓN DE CORS (ADECUADA PARA EVITAR "FAILED TO FETCH")
# Hemos añadido "Accept" y "Authorization" a los headers permitidos 
# y asegurado que los puertos 3000 y 3001 tengan acceso total.
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:3000", 
            "http://localhost:3001", 
            "http://127.0.0.1:3000", 
            "http://127.0.0.1:3001", 
            "http://51.79.18.52", 
            "http://qa.redcibercom.com"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept", "X-Requested-With"],
        "supports_credentials": True
    }
})

# 4. CONFIGURACIÓN DE MONGODB Y JWT
app.config['MONGO_URI'] = 'mongodb+srv://cibercom:proyectos2022@cluster0.ilngp.mongodb.net/controlempleados?retryWrites=true&w=majority'
app.config['CORS_HEADERS'] = 'application/json'
app.config['JWT_SECRET_KEY'] = 'cibercom'
app.config['UPLOAD_FOLDER'] = r'C:\Users\luis1\Desktop\python-mongodb-restapi\src\api\expedienteclinico_pdf'

jwt = JWTManager(app)

# 5. GESTIÓN DE SUPER ADMIN
def create_super_admin(mongo):
    try:
        super_admin = mongo.db.usuario.find_one({'role': 'SUPER_ADMIN'})
        if not super_admin:
            logger.debug("Creando cuenta maestra de Super Admin...")
            hashed_password = generate_password_hash('admin123')
            mongo.db.usuario.insert_one({
                'user': 'admin',
                'password': hashed_password,
                'role': 'SUPER_ADMIN',
                'empleado_id': None
            })
            logger.info("Super Admin 'admin' creado exitosamente.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error al verificar Super Admin: {str(e)}")
        return False

# 6. CONEXIÓN A BASE DE DATOS CON VALIDACIÓN
try:
    logger.debug("Conectando a MongoDB Atlas...")
    mongo = PyMongo(app)
    with app.app_context():
        # Ping para asegurar que la conexión es real
        mongo.db.command('ping')
        logger.info("--- CONEXIÓN EXITOSA A MONGODB ATLAS ---")
        create_super_admin(mongo)
except Exception as e:
    logger.error(f"ERROR CRÍTICO: No se pudo conectar a la base de datos: {str(e)}")
    sys.exit(1)

# 7. IMPORTACIÓN Y CONFIGURACIÓN DE RUTAS
from api.login.routes import setup_login_routes
from api.usuario.routes import setup_usuario_routes
from api.empleados.routes import setup_empleados_routes
from api.catalogodepto.routes import setup_catalogodepto_routes
from api.comportamientolaboral.routes import setup_comportamientolaboral_routes
from api.datoscontacto.routes import setup_datoscontacto_routes
from api.direccion.routes import setup_direccion_routes
from api.educacion.routes import setup_educacion_routes
from api.expedienteclinico.routes import setup_expedienteclinico_routes
from api.personascontacto.routes import setup_personascontacto_routes
from api.prestamo.routes import setup_prestamo_routes
from api.redsocial.routes import setup_redsocial_routes
from api.rh.routes import setup_rh_routes
from api.jerarquia.routes import setup_jerarquia_routes

# Inicializamos las rutas
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

# 8. MANEJO DE ERRORES GLOBAL
@app.errorhandler(404)
def not_found(error=None):
    return jsonify({
        'message': 'Ruta no encontrada: ' + request.url,
        'status': 404
    }), 404

@app.errorhandler(500)
def server_error(error=None):
    return jsonify({
        'message': 'Error interno del servidor',
        'status': 500
    }), 500

# 9. LANZAMIENTO
if __name__ == "__main__":
    logger.info("Servidor Flask levantado exitosamente.")
    # Usamos host 0.0.0.0 para permitir conexiones de red local
    app.run(debug=True, host='0.0.0.0', port=5001)