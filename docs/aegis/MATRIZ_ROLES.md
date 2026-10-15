# Matriz de roles — Empleados y Aegis

Aegis decide la identidad, el acceso al producto `empleados` y el perfil.
Empleados conserva el rol de negocio ya guardado en Mongo. Un inicio de
sesión no lo reescribe.

| Perfil que devuelve Aegis en `/v1/access` | Efecto en Empleados |
|---|---|
| `admin`, `administrador` | Perfil administrador confirmado. Si la empresa todavía no tiene cuentas locales, esa persona queda como `SUPER_ADMIN` de esa empresa, con `plataforma=false`. |
| `empleado`, `employee`, `colaborador`, `user`, o sin roles | Perfil ordinario. No se eleva, aunque la base esté vacía. Si el rol local es de gestión (`SUPER_ADMIN`, `ADMIN`, `RH`), la autorización de esa sesión baja a `EMPLOYEE`. |
| `super_admin`, `owner`, `root`, `platform`, `plataforma`, `system` y variantes | Se niega. No se traduce a `SUPER_ADMIN`. |
| Cualquier otro texto | No concede privilegios de gestión. La sesión no hereda `SUPER_ADMIN`, `ADMIN` ni `RH`. El documento en Mongo no se reescribe. |

El rol local sigue guardado en Mongo. La autorización de la sesión usa el
tope: un perfil ordinario o desconocido no mantiene gestión aunque el
documento diga `ADMIN`. Los decoradores leen `rol_efectivo` de la sesión,
no solo el rol que quedó en el JWT al entrar.

`plataforma=true` solo sale de la cuenta local que ya lo tiene y es
`SUPER_ADMIN` del tenant de la plataforma. `is_platform_operator` de
`/v1/me` no enciende esa marca.
