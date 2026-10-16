# Despliegue y reversa

Esto no deja el producto marcado como listo ni migra datos. La preparación
del producto en Aegis sigue siendo un paso aparte, después del piloto.

## Antes de desplegar

- Fijar `AEGIS_APP_ID=empleados`. No usar `principal` ni `sistemaempleados`.
- `AEGIS_API_KEY` solo cubre `AEGIS_TENANT_ID`. No es una clave global.
- `CORS_ALLOWED_ORIGINS` con los orígenes reales, separados por comas.
  Con `*` el navegador no enviará la cookie.
- `COOKIE_SAMESITE=Lax` si el front y el API comparten sitio. `None` y
  `COOKIE_SECURE=true` si están en sitios distintos y el tráfico es HTTPS.
- `TRUSTED_PROXY_HOPS` solo si hay un proxy de confianza delante.
- `AEGIS_ACCESS_CACHE_SECONDS=60` salvo que se acepte otra ventana. No es
  revocación instantánea.
- No definir `ACCESS_REQUEST_NOTIFY_EMAIL` si no hay un proceso que envíe
  el outbox. Dejarlo vacío no impide guardar la solicitud.
- `PUBLIC_REGISTRATION_ENABLED` sigue en false. El alta pública con
  contraseña no es el flujo de solicitud.

## Qué no hacer en este despliegue

- No correr migraciones sobre la base real.
- No aplicar el dry-run de vínculos.
- No retirar `herramientas-y-moldes-industriales` ni
  `herramientas_y_moldes_industriales` antes de contrastar Mongo y Aegis.
- No reinvitar, reactivar ni ampliar permisos de cuentas existentes.
- No usar la cuenta de plataforma como piloto normal.
- No marcar el producto como `ready` en Aegis desde Empleados.

## Dry-run

Exportar a un JSON local `{ "usuarios": [...], "identidades": [...] }` y
ejecutar, desde `backend`:

```
python scripts/dry_run_vinculos_aegis.py archivo.json
```

No abre `MONGO_URI`. El resultado trae empresa y app actuales y destino,
UUID, vínculo local, rol actual y propuesto, estado y conflictos. `aplicado`
queda en false.

## Reversa

- Volver al commit anterior de backend y frontend.
- Las cookies nuevas se ignoran al restaurar el código viejo; las personas
  vuelven a iniciar sesión.
- Las colecciones `sesiones`, `solicitudes_acceso`, `tenant_correspondencia`,
  `designacion_admin` y `outbox_correo` pueden quedar. No cambian `org_id`
  de los datos de negocio. Borrarlas es opcional y no forma parte de esta
  entrega.
- Los usuarios ya designados como administrador de una empresa vacía
  conservan ese rol local. Revisarlos a mano si la reversa debe deshacer
  esa designación.

## Cookies, origen y SameSite

Política de este árbol, sin marcar el producto como listo:

- No se envía el atributo `Domain`. La cookie queda en el host del API.
  No se usa el dominio padre.
- `SameSite` sale de `COOKIE_SAMESITE`. El ejemplo trae `Lax`.
- `Secure` si la petición es HTTPS, si `COOKIE_SECURE` está activo, o si
  `SameSite=None`.
- Credenciales CORS solo con `CORS_ALLOWED_ORIGINS` en lista explícita.
  El ejemplo trae `https://cibercomrh.com`. `*` no lleva cookie.
- El CSRF va en el JSON de `POST /login`, `POST /refresh` y `GET /session`.
  El front lo guarda en memoria. No lo lee de `document.cookie`.
- Un `Origin` presente que no esté en la lista recibe HTTP 403, también
  en el login. No basta con que el navegador oculte la respuesta por CORS.
- Hosts distintos no son, por sí solos, sitios distintos. Dos subdominios
  HTTPS del mismo dominio registrable pueden usar `SameSite=Lax` con
  `credentials: include` y la lista CORS explícita. En cambio,
  `https://cibercomrh.com` y un API bajo `https://redcibercom.cloud` sí son
  sitios distintos.
- El `REACT_APP_API_URL` de desarrollo local es `http://localhost:5001`.
  El hostname de producción hay que confirmarlo antes de elegir la política.
  La preferencia es un proxy del mismo origen o del mismo sitio. `SameSite=None`
  y `Secure` cubren el caso entre sitios en algunos navegadores, sin
  garantizar que acepten cookies de terceros. No se amplía `Domain`.

## Índices

`python scripts/migracion_indices_aegis.py` solo imprime los índices.
Son parciales: un usuario sin UUID y una solicitud sin clave de idempotencia
no entran al índice único. No abre la base. Aplicarlos exige
`APLICAR_INDICES_DESECHABLE=1` y una `MONGO_URI` local cuyo nombre contenga
`desechable`. Si hay duplicados, los informa y no los borra. Esta entrega
no lo ejecuta sobre la base del proyecto.
