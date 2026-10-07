# core/bancos_mx.py
# ─────────────────────────────────────────────────────────────────────────────
# Catálogo de claves de banco SPEI (los 3 primeros dígitos de la CLABE).
# Sirve para (1) rechazar CLABEs cuyo banco no existe (p. ej. 000…), (2)
# mostrar el banco que corresponde a una CLABE y (3) avisar si el banco
# capturado no coincide con el de la CLABE.
#
# No es exhaustivo (Banxico agrega participantes): una clave que no está aquí
# NO se rechaza, solo no se reconoce. Se rechazan las claves imposibles.
# ─────────────────────────────────────────────────────────────────────────────
import unicodedata

# clave: (nombre, alias para reconocer lo que la persona escribe en "Banco")
BANCOS = {
    "002": ("Citibanamex", ("banamex", "citibanamex", "citi")),
    "006": ("Bancomext", ("bancomext",)),
    "009": ("Banobras", ("banobras",)),
    "012": ("BBVA México", ("bbva", "bancomer")),
    "014": ("Santander", ("santander",)),
    "019": ("Banjército", ("banjercito",)),
    "021": ("HSBC", ("hsbc",)),
    "030": ("BanBajío", ("bajio", "banbajio")),
    "036": ("Inbursa", ("inbursa",)),
    "042": ("Mifel", ("mifel",)),
    "044": ("Scotiabank", ("scotiabank", "scotia")),
    "058": ("Banregio", ("banregio", "hey banco", "hey")),
    "059": ("Invex", ("invex",)),
    "060": ("Bansí", ("bansi",)),
    "062": ("Afirme", ("afirme",)),
    "072": ("Banorte", ("banorte",)),
    "106": ("Bank of America", ("bank of america",)),
    "108": ("MUFG", ("mufg",)),
    "110": ("J.P. Morgan", ("jp morgan", "j.p. morgan")),
    "112": ("Monex", ("monex",)),
    "113": ("Ve por Más", ("ve por mas", "bx+")),
    "127": ("Banco Azteca", ("azteca",)),
    "128": ("Autofin", ("autofin",)),
    "129": ("Barclays", ("barclays",)),
    "130": ("Compartamos", ("compartamos",)),
    "132": ("Multiva", ("multiva",)),
    "133": ("Actinver", ("actinver",)),
    "135": ("Nafin", ("nafin",)),
    "136": ("Intercam Banco", ("intercam",)),
    "137": ("BanCoppel", ("bancoppel", "coppel")),
    "138": ("ABC Capital", ("abc capital", "uala")),
    "140": ("Consubanco", ("consubanco",)),
    "141": ("Volkswagen Bank", ("volkswagen",)),
    "143": ("CIBanco", ("cibanco",)),
    "145": ("Bbase", ("bbase",)),
    "147": ("Bankaool", ("bankaool",)),
    "148": ("PagaTodo", ("pagatodo",)),
    "150": ("Inmobiliario Mexicano", ("inmobiliario",)),
    "151": ("Dondé Banco", ("donde",)),
    "152": ("Bancrea", ("bancrea",)),
    "154": ("Banco Covalto", ("covalto",)),
    "155": ("ICBC", ("icbc",)),
    "156": ("Sabadell", ("sabadell",)),
    "157": ("Shinhan", ("shinhan",)),
    "158": ("Mizuho", ("mizuho",)),
    "159": ("Bank of China", ("bank of china",)),
    "166": ("Banco del Bienestar", ("bienestar", "bansefi")),
    "168": ("Hipotecaria Federal", ("hipotecaria federal",)),
    "638": ("Nu México", ("nu", "nubank", "nu mexico")),
    "646": ("STP", ("stp",)),
    "722": ("Mercado Pago", ("mercado pago", "mercadopago")),
    "728": ("Spin by OXXO", ("spin", "oxxo")),
}


def _plano(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def banco_de_clabe(clabe):
    """Nombre del banco de una CLABE de 18 dígitos, o None si no se reconoce."""
    clave = str(clabe or "")[:3]
    return BANCOS.get(clave, (None,))[0]


def banco_capturado(nombre):
    """Clave SPEI del banco escrito a mano ("BBVA", "Banorte"…), o None."""
    plano = _plano(nombre)
    if not plano:
        return None
    for clave, (oficial, alias) in BANCOS.items():
        candidatos = {_plano(oficial), *alias}
        if plano in candidatos or any(a for a in candidatos if len(a) > 3 and a in plano):
            return clave
    return None


def catalogo():
    return [{"clave": k, "nombre": v[0]} for k, v in sorted(BANCOS.items(), key=lambda x: x[1][0])]
