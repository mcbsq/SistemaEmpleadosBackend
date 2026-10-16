# Resumen de la integración Empleados–Aegis

15 de octubre de 2026. Rama `IntegracionAegis` en los dos repositorios.

- Backend: https://github.com/mcbsq/SistemaEmpleadosBackend/tree/IntegracionAegis
- Frontend: https://github.com/mcbsq/SistemaEmpleadosFrontend/tree/IntegracionAegis

Aegis sigue siendo la autoridad de identidad, acceso al producto `empleados` y perfil. Empleados conserva los datos de negocio, el rol detallado en Mongo y los permisos de pantalla. Esta entrega no marca el producto como listo, no migra usuarios y no aplica índices sobre la base real.

Documentos de apoyo en esta misma carpeta: `CONTRATO.md`, `MATRIZ_ROLES.md` y `DESPLIEGUE.md`.

## Backend

Repositorio `SistemaEmpleadosBackend`.

### Identidad y acceso

- El cliente usa solo `app_key=empleados`. `principal` y `sistemaempleados` no sirven de respaldo.
- El login llama a Aegis. Un 404, 409, 429 o 5xx no cae al hash local ni a otra aplicación.
- Si `/v1/access` responde 403 «Password change required», se abre una sesión limitada a cambiar la contraseña y cerrar sesión. Antes eso se devolvía como 502 y la persona no podía continuar.
- El perfil `user` es ordinario, igual que `empleado`, `employee` y `colaborador`.
- Un perfil administrador confirmado (`admin`, `administrador`) solo puede designar al administrador de una empresa que todavía no tiene cuentas, y con `plataforma=false`.
- Cadenas privilegiadas desconocidas (`super_admin`, `owner`, `root`, `platform` y similares) se niegan. No se traducen a `SUPER_ADMIN`.
- Si el perfil de Aegis deja de ser administrador, la sesión deja de administrar aunque Mongo siga diciendo `SUPER_ADMIN`, `ADMIN` o `RH`. El documento de Mongo no se reescribe.
- `is_platform_operator` no enciende `plataforma`.
- El vínculo local es la pareja UUID de usuario y UUID de empresa. El login no rellena ese UUID al encontrar la primera fila. Dos filas o una fila de otra empresa son conflicto.
- Dar de baja o quitar el producto vacía el permiso de Empleados en Aegis. No desactiva la cuenta global ni llama a purge.

### Sesión, CSRF y renovación

- El navegador guarda `empleados_sid` en cookie HttpOnly, sin atributo `Domain`.
- El CSRF viaja en el JSON de login, renovación y `GET /session`. No se publica en una cookie legible.
- Con Aegis activo, el login del navegador no devuelve el JWT en el JSON.
- `POST /login/dispositivo` queda deshabilitado mientras la identidad la controla Aegis.
- La caducidad es de inactividad: renovar la alarga y una sesión vencida no se renueva.
- Antes de llamar a Aegis, la renovación toma un lease en Mongo. Así dos workers no presentan el mismo refresh. El perdedor no revoca la sesión ganadora. Si la generación nueva todavía no tiene una decisión de acceso, tampoco emite una sesión de negocio.
- Un 401 o 403 explícito cierra la sesión. Un 429, un 5xx o un fallo de red responden 503 y la conservan. Guardar el refresh nuevo no marca el acceso como válido: solo un `/v1/access` coherente actualiza esa caché. Mientras tanto, una petición de negocio no entra con una decisión fabricada.
- El rol que usan los filtros de empleados, nómina y analítica es el de la sesión, no el que quedó firmado en el JWT. Bajar de `SUPER_ADMIN` a `user` recorta áreas, plataforma y el listado, sin reescribir el token.
- Un `Origin` presente que no esté en `CORS_ALLOWED_ORIGINS` recibe HTTP 403, también en el login.
- Las rutas públicas son una lista exacta. Una petición privada sin sesión responde 401.
- La recuperación exige la página de la empresa. Sin esa liga no llama a Aegis y no dice que salió un correo.

### Solicitudes y operación

- `POST /public/access-requests` guarda la solicitud y responde 202. No crea empresa, usuario ni acceso en Aegis.
- La misma clave de idempotencia con otro contenido responde 409, sin decir si la cuenta existe.
- Solo un operador de plataforma lista y resuelve la cola. Registrar los UUID confirmados no abre datos.
- `scripts/migracion_indices_aegis.py` imprime índices parciales y no se conecta. Una cuenta sin UUID y una solicitud sin clave de idempotencia no chocan con el índice único. Si hay duplicados reales, los informa y no los borra. Aplicarlos exige una base desechable y `APLICAR_INDICES_DESECHABLE=1`.
- `scripts/dry_run_vinculos_aegis.py` lee un JSON local. No abre `MONGO_URI` y deja `aplicado` en false.

## Frontend

Repositorio `SistemaEmpleadosFrontend`.

- La sesión se recuerda con `sesion_activa`. El JWT ya no se guarda en `sessionStorage`.
- El CSRF se guarda en memoria. `GET /session` lo recupera al recargar, con la cookie de sesión. El front no lo lee de `document.cookie`, porque el API y la página pueden estar en hosts distintos.
- Las llamadas al API van con `credentials: include`.
- Si cerrar sesión falla, la pantalla no se limpia: la cookie sigue vigente y se puede reintentar.
- Tras cambiar la contraseña obligatoria, la persona vuelve al login. No entra a la aplicación con esa sesión.
- «Solicitar acceso» separa «Registrar una empresa nueva» de «Ya pertenezco a una empresa». El segundo caso no ofrece un alta con contraseña.
- El panel de solicitudes solo se muestra a la cuenta de plataforma. El texto deja claro que aprobar no crea el acceso.
- La recuperación pide abrir la página de la empresa. Sin ese enlace, el aviso es «Abre la página de tu empresa y solicita la recuperación desde ahí.»

## Qué queda fuera de esta entrega

- No se desplegó.
- No se corrió el login contra Aegis con cuentas reales.
- No se aplicaron índices ni el dry-run sobre Mongo.
- No se reinvitó, reactivó ni amplió ninguna cuenta existente.
- No se enviaron correos. El outbox solo se llena si `ACCESS_REQUEST_NOTIFY_EMAIL` tiene valor, y aun así no envía.
- La concurrencia del lease se probó con una base SQLite desechable, no con la Mongo del proyecto.
- Hosts distintos no equivalen a sitios distintos. Dos subdominios del mismo dominio registrable pueden usar `SameSite=Lax`. `https://cibercomrh.com` y un API en `https://redcibercom.cloud` sí son sitios distintos. El API local de desarrollo es `http://localhost:5001`. El hostname de producción hay que confirmarlo antes del piloto. No se amplía `Domain`.

## Cómo validar

Backend, desde `backend`:

```
python -m pytest -q --ignore=tests/test_integracion_multiempresa.py
```

Esa corrida dio 158 pruebas en verde. No incluye `tests/test_integracion_multiempresa.py`, que abre la base real.

Frontend, desde `frontend`:

```
npm test -- --watchAll=false
npm run build
```

La suite de interfaz dio 5 pruebas en verde y el build compiló.

Índices, solo lectura:

```
python scripts/migracion_indices_aegis.py
```

Imprime la lista y termina sin conectarse.
