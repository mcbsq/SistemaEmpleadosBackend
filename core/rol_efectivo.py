# Tope de autorización de la sesión. Mongo conserva el rol de negocio.
# Si Aegis ya no confirma un perfil administrador, una sesión no puede
# seguir administrando aunque el documento local siga diciendo ADMIN.
from core.perfiles_aegis import clasificar_perfiles

_GESTION = frozenset({"SUPER_ADMIN", "ADMIN", "RH"})


def acotar(rol_local, perfiles):
    """
    Rol que esta sesión puede usar.
    None significa que el perfil de Aegis está denegado.
    """
    clase = clasificar_perfiles(perfiles)
    if clase == "denegado":
        return None
    if clase == "administrador":
        return rol_local or "EMPLOYEE"
    if rol_local in _GESTION:
        return "EMPLOYEE"
    return rol_local or "EMPLOYEE"
