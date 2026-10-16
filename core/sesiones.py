# Sesión de servidor. El navegador solo guarda un identificador opaco en
# cookie HttpOnly. Los tokens de Aegis no salen de esta colección.
#
# La caché de autorización (AEGIS_ACCESS_CACHE_SECONDS, 60 s por defecto) es
# la ventana máxima en la que una revocación hecha en Aegis puede tardar en
# verse en una petición de negocio. Renovar o cerrar sesión no usa esa caché
# para alargar una sesión que Aegis ya rechazó. No es revocación instantánea.
#
# gunicorn usa varios workers. Un threading.Lock no los coordina: el lease
# vive en esta colección y se reclama con find_one_and_update antes de llamar
# a Aegis. Si el proceso muere, el lease vence y otro worker puede retomarlo.
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone

_candados = {}
_candados_guard = threading.Lock()
LEASE_SEGUNDOS = 20


def ahora():
    """Reloj de la sesión. Las pruebas lo sustituyen; el proceso usa UTC."""
    return datetime.now(timezone.utc)


def segundos_cache_acceso():
    try:
        return max(0, int(os.environ.get("AEGIS_ACCESS_CACHE_SECONDS", "60")))
    except ValueError:
        return 60


def candado_de(sid):
    """Candado local. No es la coordinación entre workers; esa es el lease."""
    with _candados_guard:
        if sid not in _candados:
            _candados[sid] = threading.Lock()
        return _candados[sid]


def _col(mongo):
    return mongo.db.raw.sesiones


def _momento(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            return valor.replace(tzinfo=timezone.utc)
        return valor
    texto = str(valor)
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    try:
        marca = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if marca.tzinfo is None:
        marca = marca.replace(tzinfo=timezone.utc)
    return marca


def _vencida(doc, momento=None):
    expira = _momento((doc or {}).get("expira_en"))
    if expira is None:
        return False
    return expira <= (momento or ahora())


def crear(mongo, *, user, org_id, claims, must_change_password=False, aegis=None, minutos=15, rol_local=None):
    momento = ahora()
    aegis = aegis or {}
    doc = {
        "sid": secrets.token_urlsafe(32),
        "csrf": secrets.token_urlsafe(24),
        "gen": 0,
        "revocada": False,
        "user": user,
        "org_id": org_id,
        "aegis_user_id": aegis.get("user_id"),
        "aegis_tenant_id": aegis.get("tenant_id"),
        "app_key": aegis.get("app_key") or "empleados",
        "access_token": aegis.get("access_token"),
        "refresh_token": aegis.get("refresh_token"),
        "must_change_password": bool(must_change_password),
        "rol_local": rol_local or claims.get("role"),
        "rol_efectivo": claims.get("role"),
        "auth_checked_at": momento.isoformat(),
        "creada_en": momento.isoformat(),
        "expira_en": (momento + timedelta(minutes=int(minutos or 15))).isoformat(),
        "lease_hasta": None,
        "lease_dueno": None,
        "claims": {
            "user": claims.get("user"),
            "role": claims.get("role"),
            "empleado_id": claims.get("empleado_id"),
            "org_id": claims.get("org_id"),
            "plataforma": bool(claims.get("plataforma")),
            "areas_administradas": claims.get("areas_administradas") or [],
        },
    }
    _col(mongo).insert_one(doc)
    return doc


def obtener(mongo, sid):
    if not sid:
        return None
    doc = _col(mongo).find_one({"sid": sid})
    if not doc or doc.get("revocada") or _vencida(doc):
        return None
    return doc


def revocar(mongo, sid):
    if not sid:
        return
    _col(mongo).update_one(
        {"sid": sid},
        {"$set": {"revocada": True, "access_token": None, "refresh_token": None, "lease_dueno": None}},
    )


def revocar_usuario(mongo, user, org_id):
    if not user:
        return
    filtro = {"user": user, "revocada": {"$ne": True}}
    if org_id:
        filtro["org_id"] = org_id
    _col(mongo).update_many(
        filtro,
        {"$set": {"revocada": True, "access_token": None, "refresh_token": None, "lease_dueno": None}},
    )


def rotar(mongo, sid, gen, tokens, must_change_password=False, minutos=None):
    """Compare-and-swap sobre gen. El perdedor de la carrera no pisa el par nuevo."""
    momento = ahora()
    campos = {
        "gen": gen + 1,
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "must_change_password": bool(must_change_password),
        "lease_hasta": None,
        "lease_dueno": None,
    }
    if minutos:
        campos["expira_en"] = (momento + timedelta(minutes=int(minutos))).isoformat()
    resultado = _col(mongo).update_one(
        {"sid": sid, "gen": gen, "revocada": {"$ne": True}},
        {"$set": campos},
    )
    return getattr(resultado, "matched_count", 0) == 1


def reclamar_lease(mongo, sid, gen, segundos=LEASE_SEGUNDOS):
    """
    Un solo worker llama a Aegis. Devuelve (documento_anterior, dueño) o (None, None).
    Un lease vencido se puede retomar: cubre un worker que murió a media renovación.
    """
    momento = ahora()
    dueno = secrets.token_hex(8)
    limite = (momento + timedelta(seconds=int(segundos))).isoformat()
    previo = _col(mongo).find_one_and_update(
        {
            "sid": sid,
            "gen": gen,
            "revocada": {"$ne": True},
            "$or": [
                {"lease_hasta": {"$exists": False}},
                {"lease_hasta": None},
                {"lease_hasta": {"$lt": momento.isoformat()}},
            ],
        },
        {"$set": {"lease_hasta": limite, "lease_dueno": dueno}},
    )
    if not previo:
        return None, None
    return previo, dueno


def soltar_lease(mongo, sid, dueno):
    if not sid or not dueno:
        return
    _col(mongo).update_one(
        {"sid": sid, "lease_dueno": dueno},
        {"$set": {"lease_hasta": None, "lease_dueno": None}},
    )


def confirmar_par(mongo, sid, gen, dueno, tokens, minutos, must_change_password=False):
    """
    Guarda el par nuevo antes de consultar /v1/access para no reutilizar el
    refresh viejo. No renueva la caché de autorización: esa decisión sigue
    pendiente hasta que /v1/access responda de forma coherente.
    """
    momento = ahora()
    expira = (momento + timedelta(minutes=int(minutos or 15))).isoformat()
    resultado = _col(mongo).update_one(
        {"sid": sid, "gen": gen, "lease_dueno": dueno, "revocada": {"$ne": True}},
        {"$set": {
            "gen": gen + 1,
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "must_change_password": bool(must_change_password),
            "auth_checked_at": None,
            "acceso_pendiente": True,
            "expira_en": expira,
            "lease_hasta": None,
            "lease_dueno": None,
        }},
    )
    return getattr(resultado, "matched_count", 0) == 1, expira


def prorrogar(mongo, sid, minutos):
    """Alarga la inactividad de una sesión que sigue vigente. No revive una vencida."""
    momento = ahora()
    doc = _col(mongo).find_one({"sid": sid, "revocada": {"$ne": True}})
    if not doc or _vencida(doc, momento):
        return None
    expira = (momento + timedelta(minutes=int(minutos or 15))).isoformat()
    _col(mongo).update_one({"sid": sid}, {"$set": {"expira_en": expira}})
    doc["expira_en"] = expira
    return doc


def fijar_rol(mongo, sesion, rol):
    if not sesion or not rol:
        return
    claims = dict(sesion.get("claims") or {})
    claims["role"] = rol
    if rol != "SUPER_ADMIN":
        claims["plataforma"] = False
    if rol != "ADMIN":
        claims["areas_administradas"] = []
    _col(mongo).update_one(
        {"sid": sesion.get("sid")},
        {"$set": {"rol_efectivo": rol, "claims": claims}},
    )
    sesion["rol_efectivo"] = rol
    sesion["claims"] = claims


def marcar_acceso(mongo, sid):
    """Solo después de un /v1/access exitoso y coherente."""
    _col(mongo).update_one(
        {"sid": sid, "revocada": {"$ne": True}},
        {"$set": {"auth_checked_at": ahora().isoformat(), "acceso_pendiente": False}},
    )


def acceso_en_cache(sesion, ahora=None, segundos=None):
    """True si la última decisión de acceso todavía está dentro de la ventana."""
    if not sesion or sesion.get("acceso_pendiente") or not sesion.get("auth_checked_at"):
        return False
    segundos = segundos_cache_acceso() if segundos is None else segundos
    momento = ahora if ahora is not None else globals()["ahora"]()
    marca = _momento(sesion["auth_checked_at"])
    if marca is None:
        return False
    return (momento - marca).total_seconds() < segundos
