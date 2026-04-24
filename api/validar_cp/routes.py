# api/validar_cp/routes.py
#
# [FEAT] Validación de código postal mexicano en tiempo real
#
# La idea del cliente (17 abr 2026):
#   - No descargar la base de datos de Correos de México
#   - Consultar en tiempo real para que siempre esté actualizado
#   - Endpoint: GET /validar-cp/<cp>
#
# Estrategia:
#   Correos de México tiene un servicio público de consulta de CPs:
#   https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/Descarga.aspx
#   Sin embargo, ese URL es para descarga masiva.
#   Para consulta individual usamos el buscador público:
#   https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/CodigoPostal.aspx
#   que acepta el CP por form POST y devuelve HTML con los resultados.
#
#   Si ese endpoint cambia o bloquea scraping, hay un fallback:
#   La API pública de SEPOMEX (requiere token gratuito):
#   https://api-sepomex.hckdrk.mx/query/info_cp/<cp>
#   (open source, no oficial, pero muy usado y actualizado)
# ─────────────────────────────────────────────────────────────────────────────

import requests
import re
import logging
from flask import jsonify
from functools import lru_cache

logger = logging.getLogger(__name__)

# URL del buscador público de Correos de México
_CORREOS_URL = (
    "https://www.correosdemexico.gob.mx"
    "/SSLServicios/ConsultaCP/CodigoPostal.aspx"
)

# Fallback: API pública de SEPOMEX (no requiere autenticación)
_SEPOMEX_URL = "https://api-sepomex.hckdrk.mx/query/info_cp/{cp}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


@lru_cache(maxsize=512)
def _consultar_correos(cp: str):
    """
    Intenta consultar el CP en Correos de México.
    Retorna dict con {valido, colonias, municipio, estado} o None si falla.
    """
    try:
        # Paso 1: GET para obtener el __VIEWSTATE (ASP.NET)
        session = requests.Session()
        resp = session.get(_CORREOS_URL, headers=HEADERS, timeout=5)
        resp.raise_for_status()

        vs  = re.search(r'__VIEWSTATE[^>]*value="([^"]*)"', resp.text)
        evv = re.search(r'__EVENTVALIDATION[^>]*value="([^"]*)"', resp.text)

        if not vs or not evv:
            return None

        # Paso 2: POST con el CP
        data = {
            "__VIEWSTATE":       vs.group(1),
            "__EVENTVALIDATION": evv.group(1),
            "ctl00$MainContent$TxtCodigo": cp,
            "ctl00$MainContent$BtnBuscar": "Buscar",
        }
        resp2 = session.post(_CORREOS_URL, data=data, headers=HEADERS, timeout=8)
        resp2.raise_for_status()

        # Si la respuesta contiene el CP, es válido
        if cp in resp2.text:
            colonias = re.findall(
                r'<span[^>]*class="[^"]*colonia[^"]*"[^>]*>([^<]+)</span>',
                resp2.text, re.IGNORECASE
            )
            municipio = re.search(
                r'<span[^>]*id="[^"]*Municipio[^"]*"[^>]*>([^<]+)</span>',
                resp2.text, re.IGNORECASE
            )
            estado = re.search(
                r'<span[^>]*id="[^"]*Estado[^"]*"[^>]*>([^<]+)</span>',
                resp2.text, re.IGNORECASE
            )
            return {
                "valido":    True,
                "colonias":  colonias or [],
                "municipio": municipio.group(1).strip() if municipio else "",
                "estado":    estado.group(1).strip()    if estado    else "",
            }
        return {"valido": False}

    except Exception as e:
        logger.warning(f"Correos MX scraping falló para CP {cp}: {e}")
        return None


def _consultar_sepomex(cp: str):
    """
    Fallback: API pública de SEPOMEX.
    No requiere autenticación. Retorna colonias, municipio, estado.
    """
    try:
        resp = requests.get(
            _SEPOMEX_URL.format(cp=cp),
            headers=HEADERS,
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and not data.get("error"):
                colonias  = [r.get("response", {}).get("asentamiento", "") for r in data if isinstance(r, dict)]
                municipio = data[0].get("response", {}).get("municipio", "") if data else ""
                estado    = data[0].get("response", {}).get("estado",    "") if data else ""
                return {
                    "valido":    True,
                    "colonias":  [c for c in colonias if c],
                    "municipio": municipio,
                    "estado":    estado,
                }
        return {"valido": False}
    except Exception as e:
        logger.warning(f"SEPOMEX falló para CP {cp}: {e}")
        return None


def validar_cp(cp: str):
    """
    Valida un código postal mexicano consultando primero Correos de México
    y usando SEPOMEX como fallback.

    Respuesta exitosa:
      {
        "valido": true,
        "cp": "06600",
        "colonias": ["Roma Norte", "Cuauhtémoc"],
        "municipio": "Cuauhtémoc",
        "estado": "Ciudad de México",
        "fuente": "correos" | "sepomex"
      }

    Respuesta inválida:
      { "valido": false, "cp": "00000" }

    Respuesta de error de servicio:
      { "error": "No se pudo consultar el CP en este momento" }, 503
    """
    cp = str(cp).strip().zfill(5)   # normalizar a 5 dígitos

    if not re.fullmatch(r'\d{5}', cp):
        return jsonify({"error": "El código postal debe tener exactamente 5 dígitos"}), 400

    # Intento 1: Correos de México
    resultado = _consultar_correos(cp)
    fuente = "correos"

    # Intento 2: SEPOMEX (fallback)
    if resultado is None:
        resultado = _consultar_sepomex(cp)
        fuente = "sepomex"

    if resultado is None:
        return jsonify({
            "error": "No se pudo consultar el código postal en este momento. Intenta de nuevo."
        }), 503

    if not resultado.get("valido"):
        return jsonify({"valido": False, "cp": cp}), 200

    return jsonify({
        "valido":    True,
        "cp":        cp,
        "colonias":  resultado.get("colonias",  []),
        "municipio": resultado.get("municipio", ""),
        "estado":    resultado.get("estado",    ""),
        "fuente":    fuente,
    }), 200


def setup_validar_cp_routes(app):
    """
    Registrar en app.py:
        from validar_cp.routes import setup_validar_cp_routes
        setup_validar_cp_routes(app)
    """
    @app.route("/validar-cp/<cp>", methods=["GET"])
    def validar_cp_route(cp):
        return validar_cp(cp)