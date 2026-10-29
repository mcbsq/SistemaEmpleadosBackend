# Equivalencia entre perfiles de Aegis (producto empleados) y roles de negocio
# de Empleados. Aegis decide identidad, acceso al producto y perfil. Empleados
# conserva el rol detallado ya guardado en Mongo: un login no lo reescribe.
#
# Un perfil administrador confirmado solo puede designar al administrador de
# ESA empresa cuando el entorno local todavía no tiene cuentas. No concede
# plataforma=true ni acceso a otras empresas. Un perfil ordinario no se eleva
# aunque la base esté vacía. Un rol desconocido que implique privilegio se
# niega; nunca se traduce a SUPER_ADMIN por defecto.

APP_KEY = "empleados"

PERFILES_ADMIN_CONFIRMADOS = frozenset({"admin", "administrador"})
PERFILES_ORDINARIOS = frozenset({"empleado", "employee", "colaborador", "user"})
ROLES_PRIVILEGIO_DESCONOCIDO = frozenset({
    "super_admin", "superadmin", "super-admin", "owner", "root",
    "platform", "plataforma", "platform_admin", "platform_operator",
    "system", "sistema",
})


def clasificar_perfiles(roles):
    """Devuelve administrador, ordinario, desconocido o denegado."""
    normalizados = set()
    for rol in roles or []:
        texto = str(rol or "").strip().lower()
        if texto:
            normalizados.add(texto)
    if normalizados & ROLES_PRIVILEGIO_DESCONOCIDO:
        return "denegado"
    if normalizados & PERFILES_ADMIN_CONFIRMADOS:
        return "administrador"
    if not normalizados or normalizados <= PERFILES_ORDINARIOS:
        return "ordinario"
    return "desconocido"


def misma_empresa_y_app(perfil, acceso, app_key=APP_KEY):
    """Identidad y decisión de acceso tienen que ser de la misma empresa y app."""
    if not isinstance(perfil, dict) or not isinstance(acceso, dict):
        return False
    if acceso.get("allowed") is not True:
        return False
    if perfil.get("is_active") is False:
        return False
    tenant = perfil.get("tenant_id")
    if not tenant or tenant != acceso.get("tenant_id"):
        return False
    if (perfil.get("app_key") or app_key) != app_key:
        return False
    if acceso.get("app_key") != app_key:
        return False
    return True
