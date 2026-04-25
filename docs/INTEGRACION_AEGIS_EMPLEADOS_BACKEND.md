# Integración Aegis en el backend Sistema Empleados

## 1. Alcance y aclaración terminológica

En el lenguaje del equipo, **“AD”** se usa en el sentido de un **directorio de identidad relativamente simple**: un lugar **central** donde viven los **usuarios**, desde el que varios **proyectos** obtienen **tokens**, **sesiones** y un modelo de **permisos** coherente, sin que cada aplicación repita su propia base de credenciales. No implica necesariamente **Microsoft Active Directory** ni LDAP; es el concepto de *single identity* interno.

**Aegis** (documentado en la carpeta `docs` de este repositorio) es la **implementación concreta** de ese directorio: microservicio FastAPI multi-tenant con JWT, refresh, scopes por aplicación, etc.

*Nota lateral:* el `docs/ROADMAP.md` de Aegis contempla, como evolución **opcional**, integrar proveedores externos (por ejemplo login OAuth / Microsoft). Eso sería una forma más de **alimentar** el mismo directorio central; el backend de empleados seguiría confiando en los **JWT emitidos por Aegis**, igual que en el diseño descrito en el resto de este documento.

---

## 2. Qué define Aegis (resumen según la documentación del repo)

| Concepto | Uso |
|----------|-----|
| `X-Tenant-Id` | Cabecera obligatoria en casi todas las rutas `/v1/*` (salvo health). |
| `X-App-Id` | Identifica la aplicación dentro del tenant; el JWT lleva `aud` alineado con esta app. |
| Login | `POST /v1/auth/login` con email + contraseña → `access_token` (JWT) + `refresh_token`. |
| Identidad | `GET /v1/me` valida el Bearer y devuelve `id`, `email`, `roles`, `scopes`, `tenant_id`, `app_key`, etc. |
| Autorización | Scopes en el token (`scp`) y en la respuesta de `/v1/me`; errores 403 por tenant/audience/scope. |
| Refresh / logout | `POST /v1/auth/refresh`, `POST /v1/auth/logout`. |

Referencias: `docs/INTEGRATION_GUIDE.md`, `docs/README.md`, `docs/ARCHITECTURE_AUDIT.md`, `docs/PLATFORM_MODEL.md`.

---

## 3. Estado actual del backend Sistema Empleados (Flask)

### 3.1 Autenticación

- **Login**: `POST /login` valida usuario y contraseña contra la colección MongoDB `usuario` (`api/login/logic.py`).
- **JWT**: `Flask-JWT-Extended` con `JWT_SECRET_KEY` fijo en código (`app.py`).
- **Claims actuales** en el token: `user`, `role`, `empleado_id`, `org_id` (objeto de identidad embebido en el JWT local).
- **Respuesta de login**: además del token, devuelve `permisos` y `modulos` calculados por rol (o personalizados en el documento de usuario).

### 3.2 Uso de `jwt_required` hoy

Solo un subconjunto de rutas exige JWT:

- `GET /usuarios` — restringido a `SUPER_ADMIN` (`api/usuario/routes.py`).
- `PATCH /empleados/<id>/aprobar` — restringido a `ADMIN` o `SUPER_ADMIN` (`api/empleados/routes.py`).

El resto de endpoints (empleados CRUD, usuario CRUD salvo el alias protegido, RH, expediente, etc.) **no** están decorados con `@jwt_required()`, por lo que la superficie expuesta depende casi por completo de la red / capa perimetral. Cualquier endurecimiento con Aegis debería ir acompañado de una **política clara de qué rutas deben ser públicas** (por ejemplo solo health/monitor) y cuáles no.

### 3.3 Brecha frente a Aegis

| Aspecto | Hoy (empleados) | Aegis |
|---------|-------------------|--------|
| Identificador de usuario | Campo `user` (string) | `email` en login; `id` UUID en `/v1/me` |
| Autorización | Rol + listas `permisos` / `modulos` en Mongo | Scopes por usuario y app (`user_app_scopes`) |
| Origen del JWT | Firmado localmente con secreto propio | Firmado por Aegis (`HS256` / `RS256` / `ES256` según despliegue) |
| Multi-tenant / app | `org_id` opcional en identidad | `X-Tenant-Id`, `X-App-Id`, claims `tid` / `aud` |

### 3.4 Modo puente (adecuado con el proyecto ~80% avanzado)

**Idea:** el JWT “de verdad” para el día a día del API de empleados puede **seguir siendo el actual** (firmado por Flask-JWT). **Aegis** se usa como **directorio central solo en el login**: credenciales y usuario lógico del ecosistema Cibercom; otros proyectos nuevos pueden consumir **directamente** el JWT de Aegis cuando convenga. Así se pospone la integración completa (validar JWT Aegis en cada request) sin bloquear la unificación de usuarios.

**Permisos:** siguen administrándose **solo en el sistema de empleados** (Mongo: `role`, `permisos`, `modulos`). En Aegis, la app **empleados** del tenant **Cibercom** puede llevar **scopes mínimos o por defecto** (p. ej. un único scope tipo `empleados:app` o incluso el mínimo necesario para que el usuario exista en esa app), **sin** intentar duplicar el modelo fino de RRHH en Aegis.

**Convivencia del CRUD de usuarios en empleados con Aegis**

| Momento | Qué hace empleados | Qué hace Aegis |
|--------|---------------------|----------------|
| **Alta** (`POST /usuario`) | Persiste en Mongo (rol, `empleado_id`, `user`/alias, **sin** hash de contraseña; ver spec Aegis). | Llama a `POST /v1/admin/users` (API key, tenant Cibercom + app empleados) con **email**, **password** (política Aegis) y opcional **`username`** alineado al campo `user` si aplica. Guarda `aegis_user_id` en Mongo. |
| **Cambio de contraseña** | No almacena secreto en Mongo; delega en Aegis (`change-password` con sesión Aegis, o `reset-password` / `PATCH` desde backend con API key según el flujo de UI acordado). | Única fuente de verdad del hash (PostgreSQL / Argon2 en Aegis). |
| **Baja** | Borra o desactiva en Mongo. | Desactivar usuario en Aegis o borrar según política; evita que entre al ecosistema con el mismo email. |
| **Cambio de rol / permisos** | Solo Mongo. | Opcional: no tocar Aegis; los scopes allí pueden quedar fijos en el mínimo. |

**Orden recomendado en alta:** escribir primero en **Aegis** y luego en Mongo **solo si** quieres que nunca exista fila local sin identidad central; si el equipo prefiere no fallar el CRUD por caída de Aegis, orden inverso: **Mongo primero**, luego Aegis, con **reintento / cola** si Aegis falla y marca `sync_aegis_pending` en el documento usuario.

**Login:** `POST /login` deja de comprobar solo `check_password_hash` contra Mongo; reenvía a `POST /v1/auth/login` de Aegis (tenant Cibercom, `X-App-Id` = app empleados) el cuerpo **`identifier` + `password`**: el `identifier` puede ser el **correo completo** o la **parte local** antes de `@` (ej. `mgalvezv` para `mgalvezv@redcibercom.com.mx`), según el contrato implementado en Aegis. Si es correcto, resuelve el `usuario` Mongo por `aegis_user_id` o email y emite el **JWT local** con la misma forma de `identity` que hoy (`user`, `role`, `empleado_id`, …). Si Aegis no responde, se puede definir un **fallback** temporal (login local) hasta estabilizar operación.

Los cambios en **Aegis** están en **`docs/AEGIS_SPEC_INTEGRACION_EMPLEADOS.md`**; para **copiar al repo Aegis y crear issues**, usar **`docs/AEGIS_PORTING_AL_REPO.md`**.

---

## 4. Objetivos de la integración

1. **Un solo login** con el ecosistema interno: el front (en una fase posterior) obtiene tokens desde Aegis y los reutiliza contra el backend de empleados.
2. **Validar** en el backend de empleados que el `access_token` es emitido por Aegis, corresponde al tenant y app configurados, y (opcionalmente) que tiene los scopes necesarios por endpoint — **objetivo aplazable** si se adopta el **modo puente** (sección 3.4): entonces solo el **login** habla con Aegis y el API sigue validando el JWT local.
3. **Mapear** la identidad Aegis (`email` o `sub`/`id`) al modelo actual (`usuario` en Mongo, `empleado_id`, `role`, `permisos`) para no reescribir toda la lógica de negocio de golpe.
4. **Reducir** dependencia del endpoint `/login` local a medio plazo, sin un “big bang” obligatorio si se diseña un periodo de convivencia.

---

## 5. Opciones de validación del token en el backend

### 5.1 Validación local del JWT (recomendada en producción)

- Obtener de Aegis el **mismo algoritmo y clave** que usa el despliegue (`JWT_SECRET` para HS256, o `JWT_PUBLIC_KEY` para RS256/ES256).
- Con `PyJWT` (ya en `requirements.txt`), verificar firma, `exp`, `aud` (debe coincidir con el `app_key` de empleados en Aegis), `tid` o claim de tenant si Aegis lo incluye, e iss si está definido.
- **Ventaja**: sin latencia extra ni dependencia de Aegis en cada request.
- **Requisito**: proceso operativo para rotación de claves alineado con Aegis (`docs/ROADMAP.md` menciona evolución con `kid`).

### 5.2 Introspección con `GET /v1/me`

- Reenviar `Authorization`, `X-Tenant-Id`, `X-App-Id` a Aegis.
- **Ventaja**: implementación rápida; siempre coherente con revocaciones y estado del usuario en Aegis.
- **Inconveniente**: carga, latencia y punto de fallo; conviene cache corta con invalidación ante 401.

### 5.3 Híbrido

- Validar JWT en local y, en operaciones sensibles o de forma periódica, confirmar con `/v1/me` (según política de riesgo).

---

## 6. Modelo de autorización: scopes Aegis ↔ permisos actuales

Los permisos funcionales del sistema (`ver_empleados`, `crud_empleados`, etc.) viven hoy en código y en Mongo. Aegis maneja **scopes** distintos (`users:read`, `apps:manage`, …) orientados a administración de la plataforma de identidad.

**Recomendación:**

1. En Aegis, registrar una **app** dedicada (por ejemplo `empleados` o `sistema_empleados`) por tenant.
2. Definir **scopes de aplicación** para empleados (convendrá acordarlos con el equipo de Aegis; pueden ser prefijados, p. ej. `empleados:read`, `empleados:write`, `empleados:aprobar`, …) y asignarlos en `user_app_scopes`.
3. En el backend, mantener una **tabla de mapeo** scope → permisos lógicos actuales, o bien seguir leyendo `permisos`/`role` desde Mongo **después** de resolver el usuario por email/`aegis_user_id`.

Así se evita mezclar scopes de “admin de Aegis” con permisos del dominio RRHH.

En el **modo puente** (3.4), basta con **scopes por defecto** en la app empleados del tenant Cibercom; no hace falta modelar cada permiso RRHH en Aegis.

---

## 7. Resolución de usuario en Mongo

Pasos típicos tras validar el JWT:

1. Extraer `email` (o `sub`) del token o de `/v1/me`.
2. Buscar `usuario` en Mongo por:
   - nuevo campo `aegis_user_id`, o
   - campo `user` igual al email corporativo, o
   - tabla de vínculo explícita.
3. Si no existe usuario local:
   - **Política A**: denegar acceso hasta que un admin cree el vínculo (más control).
   - **Política B**: creación JIT con rol por defecto (más ágil, más riesgo).

El campo `empleado_id` y `org_id` deben seguir poblando la identidad que el resto del código espera (similar al diccionario que hoy se guarda en el JWT con `create_access_token`).

---

## 8. Convivencia con el login actual

| Fase | Comportamiento |
|------|----------------|
| **0 – Preparación** | Variables de entorno para URL de Aegis, tenant, app id, clave pública/secreto JWT; endurecer CORS si el front envía cabeceras extra. |
| **1 – Doble emisor** | El backend acepta JWT firmado por Aegis **o** (temporalmente) el JWT legacy, distinguible por `iss`, `kid` o prefijo de claim. |
| **2 – Preferencia Aegis** | Solo tokens Aegis en rutas nuevas o en middleware global; `/login` local solo para scripts o emergencia. |
| **3 – Solo Aegis** | Eliminar emisión de JWT local y deprecar `/login` o dejarlo como proxy opcional a `POST /v1/auth/login`. |

El front, según `INTEGRATION_GUIDE`, debe enviar `Authorization: Bearer <access_token>`; si el backend debe validar tenant/app alineados con Aegis, el front puede reenviar también `X-Tenant-Id` y `X-App-Id` o el backend puede fijarlos por configuración si hay un solo tenant/app por despliegue.

---

## 9. Plan de implementación por entregables

### Fase A — Diseño y Aegis (infra / producto)

- [ ] Crear en Aegis el tenant y la app “empleados” (o el nombre acordado).
- [ ] Definir scopes para la app (plantilla completa **o** mínimo por defecto si aplica modo puente, sección 3.4) y asignarlos a usuarios de prueba.
- [ ] Documentar URL base DEV (VPS), algoritmo JWT y cómo obtener la clave pública o el secreto para validación en Flask (sin commitear secretos).

### Fase B — Backend: configuración y cliente

- [ ] Externalizar `JWT_SECRET_KEY`, URI de Mongo y demás secretos a variables de entorno.
- [ ] Añadir módulo de configuración (`AEGIS_ISSUER`, `AEGIS_JWKS_URL` o clave estática, `AEGIS_EXPECTED_AUD`, `AEGIS_TENANT_ID`, timeouts).
- [ ] Implementar `validate_aegis_token(token) -> claims` (PyJWT) o cliente HTTP para `/v1/me` según la opción elegida en la sección 5.

### Fase C — Identidad unificada en Flask

- [ ] Implementar un **middleware** o **decorador** `@require_auth` que:
  - valide el Bearer,
  - cargue el `usuario` Mongo vinculado,
  - exponga en `g` (o similar) `current_user`, `empleado_id`, `role`, `permisos` resueltos.
- [ ] Unificar la forma de identidad que hoy obtienen `get_jwt_identity()` para que el código existente siga funcionando con datos resueltos post-validación Aegis.

### Fase D — Protección de rutas

- [ ] Inventario de rutas: clasificar públicas vs autenticadas vs por rol/scope.
- [ ] Aplicar el decorador/middleware a todas las rutas que deben estar protegidas (hoy la mayoría no lo está).
- [ ] Sustituir o ampliar `require_super_admin` / `require_admin` para usar scopes Aegis y/o roles Mongo según la política acordada.

### Fase E — Login y respuesta compatible con el front

- [ ] Decidir si el front llamará directamente a Aegis para login o si el backend expone un `POST /auth/aegis-login` que haga de proxy (útil para no exponer detalles en el cliente).
- [ ] Ajustar el contrato de respuesta post-login para que el front reciba la misma forma de `permisos` / `modulos` que hoy, ya sea:
  - calculados en backend tras resolver Mongo, o
  - derivados solo de scopes (con mapeo explícito).

### Fase F — Operación y calidad

- [ ] Tests automatizados con JWT de prueba (fixtures firmadas o mock de Aegis).
- [ ] Logging con `X-Request-ID` cuando se proxee a Aegis (alineado con la guía de errores RFC 7807).
- [ ] Plan de migración de usuarios: sincronización de emails, reset de contraseñas en Aegis, comunicación al equipo.

---

## 10. Variables de entorno (backend — implementación actual)

| Variable | Obligatoria si… | Descripción |
|----------|-------------------|-------------|
| `AEGIS_BASE_URL` | Login Aegis | URL base sin barra final, p. ej. `https://auth.ejemplo.com` |
| `AEGIS_TENANT_ID` | Login Aegis | Cabecera `X-Tenant-Id` (ej. slug del tenant Cibercom) |
| `AEGIS_APP_ID` | Login Aegis | `key` de la app empleados en Aegis |
| `AEGIS_API_KEY` | Alta/reset de usuarios vía Admin API | `Authorization: ApiKey …` con scopes `users:manage` (y lectura si aplica) |
| `AEGIS_TIMEOUT` | Opcional | Segundos para HTTP (default `15`) |
| `AEGIS_LEGACY_LOGIN_FALLBACK` | Opcional | `true` para volver a validar contraseña en Mongo si Aegis devuelve 401 o 503 |
| `AEGIS_DISABLED` | Opcional | `true` fuerza modo solo Mongo aunque existan URL/tenant/app |

Si `BASE_URL` + `TENANT_ID` + `APP_ID` están definidos y `AEGIS_DISABLED` no es verdadero, **`POST /login` delega en Aegis** y luego resuelve el usuario en Mongo (`aegis_user_id`, `email` o `user` = parte local). Sin `AEGIS_API_KEY`, **`POST /usuario` devuelve 503** en ese modo (no se puede provisionar contraseña solo en Mongo de forma coherente).

**`POST /usuario` con Aegis:** el JSON debe incluir **`email`** (correo completo) además de `user`, `password`, etc. La contraseña cumple la política de Aegis; la respuesta de error de validación puede propagarse.

**`seed.py`:** con `AEGIS_API_KEY` definida crea usuarios en Aegis y en Mongo (`email`, `aegis_user_id`, sin `password`). Correo por cuenta: campo opcional `email` en `CUENTAS` o `{user}@redcibercom.com.mx` vía `SEED_EMAIL_DOMAIN` (default `redcibercom.com.mx`). Sin API key pero con login Aegis, el seed **no** crea usuarios y muestra un aviso.

### Ejemplo (PowerShell) — activar Aegis localmente sin commitear secretos

> **No** pegues la API key en archivos del repo. Pásala por variables de entorno o por un secret manager.

```powershell
# Configura Aegis (IdP) para este backend
$env:AEGIS_BASE_URL="https://auth.tu-dominio.com"
$env:AEGIS_TENANT_ID="cibercom"
$env:AEGIS_APP_ID="empleados"

# API key con scopes admin (p. ej. users:manage) para alta/reset desde este backend
$env:AEGIS_API_KEY="ak_test_REEMPLAZAR_POR_TU_KEY"

# Opcionales
$env:AEGIS_TIMEOUT="15"
$env:AEGIS_LEGACY_LOGIN_FALLBACK="false"   # true solo mientras migras
$env:AEGIS_DISABLED="false"

# (Opcional) URI de Mongo si no usas la embebida en app.py / seed.py
# $env:MONGO_URI="mongodb+srv://..."

# Crear cuentas demo (Aegis + Mongo, según modo) y levantar backend
python seed.py
python app.py
```

### Ejemplo (`.env` local) — alternativa a PowerShell

Si prefieres un archivo `.env`, úsalo **solo en tu máquina** y asegúrate de que esté **ignorado por git** (por ejemplo en `.gitignore`: `.env`, `.env.local`).

Ejemplo de `.env.local` (valores ilustrativos):

```dotenv
AEGIS_BASE_URL=https://auth.tu-dominio.com
AEGIS_TENANT_ID=cibercom
AEGIS_APP_ID=empleados
AEGIS_API_KEY=ak_test_REEMPLAZAR_POR_TU_KEY

AEGIS_TIMEOUT=15
AEGIS_LEGACY_LOGIN_FALLBACK=false
AEGIS_DISABLED=false
```

> Nota: este backend (Flask) no carga `.env` automáticamente; necesitas cargarlo tú (PowerShell, tu runner, Docker, o una herramienta tipo `python-dotenv` si decides incorporarla).

---

## 11. Riesgos y dependencias

- **Desalineación email**: si en Mongo `user` no es el email corporativo, hace falta migración de datos o campo de enlace.
- **Rotación de claves JWT en Aegis**: el backend debe poder actualizar claves sin redeploy largo (JWKS o despliegue coordinado).
- **Superficie sin autenticar**: hasta no aplicar la Fase D, integrar solo Aegis en `/login` no protege el resto de la API.
- **Login vía proveedor externo** (si Aegis lo añade): el backend de empleados sigue centrado en “validar JWT de Aegis”; el flujo de redirección o federación queda en Aegis y en el front.

---

## 12. Referencias internas del repo

| Documento | Contenido |
|-----------|-----------|
| `docs/AEGIS_SPEC_INTEGRACION_EMPLEADOS.md` | Spec-driven: login con `identifier` (email o parte local), Postgres, DoD. |
| `docs/AEGIS_PORTING_AL_REPO.md` | Cómo portar el spec al repo Aegis + tickets (AEGIS-EMP-1 … 5). |
| `docs/INTEGRATION_GUIDE.md` | Flujo login, refresh, cabeceras, ejemplos Python/JS. |
| `docs/ARCHITECTURE_AUDIT.md` | Módulos Aegis, RLS, scopes en JWT. |
| `docs/PLATFORM_MODEL.md` | Tenants, apps, convenios, roles operativos. |
| `docs/ROADMAP.md` | Evolución de JWT y OAuth (opcional). |
| `api/login/logic.py` | Lógica actual de login y permisos por rol. |
| `app.py` | JWT local y arranque de la app. |
| `api/usuario/routes.py`, `api/empleados/routes.py` | Uso actual de `jwt_required`. |

---

*Documento generado como base para alinear al equipo de backend con el modelo de Aegis descrito en `docs/`. Debe actualizarse cuando se concreten nombres de app, scopes y política de rutas públicas.*
