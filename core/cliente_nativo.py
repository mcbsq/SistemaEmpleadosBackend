# La app móvil no tiene cookies de navegador ni document: guarda su token en
# el almacenamiento seguro del teléfono y lo manda como Bearer. Se reconoce
# por el encabezado X-Cliente y porque no manda Origin — un navegador siempre
# manda Origin en un POST entre sitios, así que una página no puede hacerse
# pasar por la app para recibir el JWT en el JSON.
from flask import has_request_context, request

CLIENTE_MOVIL = "empleados-movil"


def es_cliente_nativo():
    if not has_request_context():
        return False
    return (request.headers.get("X-Cliente") or "").strip() == CLIENTE_MOVIL and not request.headers.get("Origin")
