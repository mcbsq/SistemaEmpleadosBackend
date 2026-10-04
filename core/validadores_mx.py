# core/validadores_mx.py
# ─────────────────────────────────────────────────────────────────────────────
# Validación OFFLINE de identificadores oficiales mexicanos: estructura y
# dígito verificador. No consulta RENAPO/SAT/IMSS (eso requiere un proveedor
# contratado — fase 5 de la estrategia), pero sí atrapa el 95% de los errores
# reales de captura: un dígito cambiado, una letra de más, CLABE copiada mal.
#
# Cada función devuelve None si el valor es válido (o viene vacío — los campos
# son opcionales) y un mensaje en español si no lo es.
# ─────────────────────────────────────────────────────────────────────────────
import re

_CURP_RE = re.compile(
    r"^[A-Z][AEIOUX][A-Z]{2}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[HMX]"
    r"(AS|BC|BS|CC|CL|CM|CS|CH|DF|DG|GT|GR|HG|JC|MC|MN|MS|NT|NL|OC|PL|QT|QR|SP|SL|SR|TC|TS|TL|VZ|YN|ZS|NE)"
    r"[B-DF-HJ-NP-TV-Z]{3}[A-Z\d]\d$"
)
_CURP_DICC = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"

_RFC_RE = re.compile(r"^([A-ZÑ&]{3,4})\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[A-Z\d]{2}[A\d]$")


def _limpio(valor):
    return re.sub(r"\s+", "", str(valor or "")).upper()


def validar_curp(valor):
    curp = _limpio(valor)
    if not curp:
        return None
    if len(curp) != 18:
        return "La CURP debe tener 18 caracteres."
    if not _CURP_RE.match(curp):
        return "La CURP no tiene un formato válido."
    suma = sum(_CURP_DICC.index(c) * (18 - i) for i, c in enumerate(curp[:17]))
    digito = (10 - suma % 10) % 10
    if str(digito) != curp[17]:
        return "El dígito verificador de la CURP no coincide; revisa que esté bien escrita."
    return None


def validar_rfc(valor):
    rfc = _limpio(valor)
    if not rfc:
        return None
    if len(rfc) not in (12, 13):
        return "El RFC debe tener 13 caracteres (persona física) o 12 (persona moral)."
    if not _RFC_RE.match(rfc):
        return "El RFC no tiene un formato válido."
    return None


def validar_nss(valor):
    nss = _limpio(valor)
    if not nss:
        return None
    if not re.fullmatch(r"\d{11}", nss):
        return "El NSS debe tener 11 dígitos."
    # Algoritmo de Luhn sobre los primeros 10 dígitos.
    suma = 0
    for i, c in enumerate(nss[:10]):
        d = int(c) * (2 if i % 2 else 1)
        suma += d - 9 if d > 9 else d
    if (10 - suma % 10) % 10 != int(nss[10]):
        return "El dígito verificador del NSS no coincide; revisa que esté bien escrito."
    return None


def validar_clabe(valor):
    clabe = _limpio(valor)
    if not clabe:
        return None
    if not re.fullmatch(r"\d{18}", clabe):
        return "La CLABE debe tener 18 dígitos."
    pesos = (3, 7, 1) * 6
    suma = sum((int(c) * pesos[i]) % 10 for i, c in enumerate(clabe[:17]))
    if (10 - suma % 10) % 10 != int(clabe[17]):
        return "El dígito de control de la CLABE no coincide; revisa que esté bien copiada."
    return None


VALIDADORES_RH = {
    "CURP":  validar_curp,
    "RFC":   validar_rfc,
    "NSS":   validar_nss,
    "CLABE": validar_clabe,
}


def validar_campos(data, validadores=VALIDADORES_RH):
    """{campo: mensaje} con los errores encontrados en `data` (dict)."""
    errores = {}
    for campo, fn in validadores.items():
        if campo in data:
            msg = fn(data.get(campo))
            if msg:
                errores[campo] = msg
    return errores


def normalizar(valor):
    """Mayúsculas y sin espacios — así se guardan estos identificadores."""
    return _limpio(valor)


# ── Coherencia entre identificadores y datos de la persona ──────────────────
# La CURP se construye con los datos de la persona: 1ª letra y 1ª vocal
# interna del apellido paterno, 1ª letra del materno, 1ª del nombre y la
# fecha de nacimiento (AAMMDD). El RFC de persona física comparte esos mismos
# 10 caracteres. Si no coinciden, el dato es de otra persona o está mal.
import unicodedata as _ud

_PARTICULAS = {"DA", "DAS", "DE", "DEL", "DER", "DI", "DIE", "DD", "EL", "LA", "LOS", "LAS", "LE", "LES", "MAC", "MC", "VAN", "VON", "Y"}
_NOMBRES_COMUNES = {"JOSE", "J", "MARIA", "MA", "MA.", "J."}


def _plano(t):
    t = _ud.normalize("NFD", str(t or "").upper())
    t = "".join(c for c in t if _ud.category(c) != "Mn" or c == "̃")
    return t.replace("Ñ", "X").replace("Ñ", "X")


def _palabras(t, quitar_nombres=False):
    ps = [p for p in re.split(r"[\s\-]+", _plano(t)) if p and p not in _PARTICULAS]
    if quitar_nombres and len(ps) > 1 and ps[0] in _NOMBRES_COMUNES:
        ps = ps[1:]
    return ps


def coherencia_identidad(curp="", rfc="", nombre="", ap_paterno="", ap_materno="", fecha_nac=""):
    """{campo: mensaje} con las incoherencias encontradas (solo lo verificable)."""
    errores = {}
    curp, rfc = normalizar(curp), normalizar(rfc)
    if curp and len(curp) == 18:
        pat = _palabras(ap_paterno)
        if pat and curp[0] != pat[0][0]:
            errores["CURP"] = "La CURP no corresponde al apellido paterno registrado."
        nom = _palabras(nombre, quitar_nombres=True)
        if "CURP" not in errores and nom and curp[3] != nom[0][0]:
            errores["CURP"] = "La CURP no corresponde al nombre registrado."
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(fecha_nac or ""))
        if "CURP" not in errores and m and curp[4:10] != m.group(1)[2:] + m.group(2) + m.group(3):
            errores["CURP"] = "La fecha de nacimiento dentro de la CURP no coincide con la registrada."
    if rfc and len(rfc) == 13 and curp and len(curp) == 18 and rfc[:10] != curp[:10]:
        errores["RFC"] = "El RFC no corresponde a la CURP (los primeros 10 caracteres deben coincidir)."
    return errores
