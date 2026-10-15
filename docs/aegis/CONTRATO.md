# Diferencias con OpenAPI de Aegis 0.1.0

Consultado en `https://aegis.redcibercom.cloud/openapi.json` el 15 de octubre
de 2026. Donde el contrato escrito del consumidor y el OpenAPI no coinciden,
se envía lo que el OpenAPI declara y, si el consumidor ya exigía un header
de tenant, también ese header. No se inventaron campos ni rutas.

| Operación | OpenAPI | Qué hace Empleados |
|---|---|---|
| `POST /v1/auth/login` | Solo declara `X-App-Id` opcional. El cuerpo es `LoginRequest`. | Envía `X-Tenant-Id` y `X-App-Id: empleados`, como el contrato del consumidor. No cambia a `principal` ni a `sistemaempleados`. |
| `POST /v1/auth/refresh` | `X-App-Id` obligatorio. No declara `X-Tenant-Id`. | Envía ambos. Guarda el par nuevo. |
| `POST /v1/auth/logout` | Cuerpo `refresh_token`. No declara `X-Tenant-Id`. Respuesta 204. | Envía el cuerpo y `X-Tenant-Id`. Un 204 vacío es éxito. |
| `POST /v1/auth/password-reset/request` | Cuerpo `email`. No declara `X-Tenant-Id`. Siempre 202. | Envía el correo y el `X-Tenant-Id` de la liga conocida. No llama a `resolve-tenant`. |
| `POST /v1/auth/password-reset/confirm` | `token` y `new_password` (12–256). | Empleados no tiene formulario. La persona elige la contraseña en `/admin/recover` de Aegis. |
| `POST /v1/auth/change-password` | Longitud 12–256. No declara clases de carácter. | Empleados exige además mayúscula, minúscula, número y símbolo, y deja que Aegis rechace lo demás. |
| `GET /v1/access` | `allowed`, `tenant_id` (UUID), `app_key`, `mode`, `scopes`, `roles`. | El acceso a negocio exige `allowed` y el mismo UUID de empresa y `app_key` que `/v1/me`. No hay campo de preparación en esta respuesta: si el producto no está listo, Aegis debe responder `allowed=false`. |
| `PATCH /v1/admin/users/{id}` | `is_active` y `app_permissions_patch` son independientes. | Retirar Empleados manda `app_permissions_patch` vacío para esta app. No manda `is_active=false` ni usa `/users/purge`. |
| `POST /v1/platform/onboarding/company` | Operador de plataforma. | No lo llama este producto. La solicitud pública es `POST /public/access-requests`, local de Empleados. |

La ventana `AEGIS_ACCESS_CACHE_SECONDS` (60 segundos por defecto) es lo
máximo que una revocación hecha en Aegis puede tardar en verse en una
petición de negocio. `/refresh` y `/logout` no usan esa caché para alargar
una sesión rechazada.
