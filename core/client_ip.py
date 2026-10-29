# La IP de límite de frecuencia solo sale de X-Forwarded-For cuando el
# despliegue declara cuántos proxies de confianza hay delante. Si no, se usa
# la dirección que ve el proceso y se ignora el header (un cliente no puede
# elegir su propia cuota).
import os


def ip_cliente(peticion):
    try:
        saltos = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
    except ValueError:
        saltos = 0
    remoto = (getattr(peticion, "remote_addr", None) or "unknown").strip()
    if saltos <= 0:
        return remoto or "unknown"
    crudo = peticion.headers.get("X-Forwarded-For") or ""
    partes = [p.strip() for p in crudo.split(",") if p.strip()]
    if not partes:
        return remoto or "unknown"
    indice = len(partes) - saltos
    if indice < 0:
        indice = 0
    return partes[indice]
