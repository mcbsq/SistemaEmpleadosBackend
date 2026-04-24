# api/catalogos/catalogos.py
#
# Catálogos centralizados del sistema de empleados.
# Puedes exponerlos como un endpoint GET /catalogos o importarlos
# directamente en las rutas que los necesiten.
#
# NUEVO 17 abr 2026:
#  - PARENTESCO          (para personas de contacto de emergencia)
#  - ESQUEMA_CONTRATACION (para expediente laboral / RH)
#  - TIPO_VIALIDAD       (según documento anexo_l_22112024)
#    → Solo vialidades donde una persona puede ubicar su domicilio
# ──────────────────────────────────────────────────────────────────────────────

PARENTESCO = [
    "Esposa",
    "Esposo",
    "Madre",
    "Padre",
    "Amistad",
    "Hermana",
    "Hermano",
    "Prima",
    "Primo",
    "Tía",
    "Tío",
    "Abuela",
    "Abuelo",
]

ESQUEMA_CONTRATACION = [
    "Nómina",
    "Asimilados",
    "Servicios profesionales",
]

# Vialidades donde una persona puede ubicar su domicilio
# Fuente: anexo_l_22112024 Tipos Vialidad.pdf
# Solo se incluyen las que aplican a direcciones habitacionales/comerciales
TIPO_VIALIDAD = [
    "Andador",
    "Avenida",
    "Boulevard",
    "Calle",
    "Callejón",
    "Calzada",
    "Camino",
    "Carretera",
    "Cerrada",
    "Circuito",
    "Circunvalación",
    "Corredor",
    "Diagonal",
    "Eje vial",
    "Pasaje",
    "Peatonal",
    "Periférico",
    "Privada",
    "Prolongación",
    "Retorno",
    "Viaducto",
]


def setup_catalogos_routes(app):
    """
    Exponer todos los catálogos en un solo endpoint.
    Registrar en app.py:
        from catalogos.catalogos import setup_catalogos_routes
        setup_catalogos_routes(app)

    Uso en frontend:
        GET /catalogos
        → { parentesco: [...], esquema_contratacion: [...], tipo_vialidad: [...] }
    """
    from flask import jsonify

    @app.route("/catalogos", methods=["GET"])
    def get_catalogos():
        return jsonify({
            "parentesco":           PARENTESCO,
            "esquema_contratacion": ESQUEMA_CONTRATACION,
            "tipo_vialidad":        TIPO_VIALIDAD,
        }), 200