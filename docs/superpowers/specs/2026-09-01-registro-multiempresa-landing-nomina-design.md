# Registro multiempresa, landing y consulta de nómina

## Objetivo

Convertir CibercomHR en un producto de alta autoservicio: cualquier empresa puede registrarse gratuitamente, obtener una URL `cibercomrh.com/<slug>` y operar en un espacio aislado. La empresa histórica conserva el slug `cibercom` y todos sus datos. La sección Nómina pasa de calculador interno a una tabla de consulta preparada para consumir, más adelante, la API del sistema de facturación.

## Alcance

El cambio abarca los repositorios hermanos actuales:

- `SistemaEmpleadosFrontend/SistemaEmpleadosFrontend`: landing pública, formulario de registro, resolución de rutas por slug y tabla de nómina.
- `SistemaEmpleadosBackend/SistemaEmpleadosBackend`: aprovisionamiento, catálogo de tenants, protección multiempresa, migración histórica y contrato de proveedor de nómina.

Los ZIP del directorio padre son copias antiguas y quedan fuera del alcance.

## Restricciones globales

- No eliminar, reemplazar ni vaciar documentos o colecciones existentes.
- Todo documento histórico sin `org_id` pertenece a `cibercom`.
- No sobrescribir documentos que ya tengan `org_id`.
- Mantener `/Login` durante la transición.
- Mantener la línea visual existente: tokens, tipografía, colores, tarjetas, espaciado y microinteracciones actuales de CibercomHR.
- No inventar el contrato del sistema de facturación ni mostrar nóminas ficticias en producción.
- Las API keys se cifran en backend y nunca regresan al navegador.

## Arquitectura elegida

Se conserva una base MongoDB compartida con aislamiento lógico por `org_id`. `core/tenant_db.py` sigue siendo el punto central que agrega el tenant a lecturas y escrituras. Se descartan bases o colecciones separadas por empresa porque aumentarían el costo operativo y duplicarían el modelo existente.

El slug sólo selecciona la pantalla pública de entrada. El acceso a datos privados depende exclusivamente del `org_id` firmado en el JWT después de autenticar contra Aegis. Ningún endpoint privado aceptará el slug como autoridad de tenant.

## Rutas públicas

- `/`: landing comercial de CibercomHR.
- `/registro`: formulario de alta autoservicio.
- `/<slug>`: login con nombre y branding de la empresa.
- `/Login`: login genérico compatible con enlaces existentes.

Los segmentos internos (`login`, `registro`, `dashboard`, `empleados`, `vacaciones`, `nomina`, `reclutamiento`, `desempeno`, `analitica`, `settings`, `roles`, `cuentas`, `integraciones`, `monitor`, `perfil`, `tenants` y `api`) son slugs reservados. La comparación ignora mayúsculas, acentos y espacios después de normalizar el valor.

## Landing

La landing explica el producto de RH con capacidades que ya existen: directorio de empleados, expedientes, organigrama, vacaciones, roles, reclutamiento, desempeño, analítica e integraciones. No mostrará testimonios, cifras de clientes, precios o garantías no proporcionadas. Sus llamadas principales llevan a `/registro`; el acceso para clientes existentes lleva a `/Login`.

La implementación reutiliza `design-tokens.css` y patrones CSS existentes. No incorpora un nuevo framework visual.

## Registro autoservicio

El formulario solicita:

- nombre de la empresa;
- slug sugerido, editable;
- nombre del administrador;
- correo del administrador;
- contraseña y confirmación.

El frontend valida formato y confirmación para dar respuesta inmediata. El backend repite todas las validaciones, normaliza el slug y determina de forma autoritativa su disponibilidad.

### Contrato HTTP

`GET /public/tenants/slug-availability?slug=<slug>` devuelve:

```json
{ "slug": "empresa-ejemplo", "available": true }
```

`POST /public/tenants/register` recibe:

```json
{
  "company_name": "Empresa Ejemplo",
  "slug": "empresa-ejemplo",
  "admin_name": "Ana Pérez",
  "admin_email": "ana@ejemplo.com",
  "password": "contraseña elegida"
}
```

Una respuesta exitosa usa HTTP 201:

```json
{
  "slug": "empresa-ejemplo",
  "status": "active",
  "login_url": "/empresa-ejemplo"
}
```

Los errores usan códigos estables (`slug_unavailable`, `email_unavailable`, `invalid_registration`, `identity_provider_unavailable`, `provisioning_failed`) y mensajes seguros en español.

### Aprovisionamiento coordinado

MongoDB y Aegis no ofrecen una transacción compartida. El backend usa un registro global `tenant_provisioning` con clave única por slug y los estados `provisioning`, `active` y `failed`. Cada operación conserva identificadores externos para poder reintentarse sin duplicar recursos.

El orden es:

1. Insertar o retomar el registro de aprovisionamiento y reservar el slug.
2. Crear o recuperar el tenant y la aplicación `empleados` en Aegis mediante un adaptador dedicado.
3. Crear o recuperar la identidad del administrador en ese tenant.
4. Crear la configuración inicial de organización.
5. Crear el usuario Mongo `SUPER_ADMIN` dentro del nuevo `org_id`.
6. Registrar el tenant global con `estado: active` y finalizar el aprovisionamiento.

El cliente Aegis expondrá una interfaz local y testeable; URL, credencial de servicio y timeout procederán de variables de entorno. Mientras el contrato real de aprovisionamiento de Aegis no esté disponible o configurado, el endpoint fallará con `identity_provider_unavailable` y no activará una empresa parcial. No se fijará en el frontend ninguna URL o credencial de Aegis.

Una repetición con la misma información devuelve el resultado existente si ya está activo. Un slug reservado por otro correo responde 409. Los fallos se registran para soporte sin guardar contraseñas.

## Empresa histórica

`cibercom` es el slug definitivo de la organización actual. Una migración explícita e idempotente:

1. enumera las colecciones operativas conocidas;
2. reporta conteo total, con `org_id`, sin `org_id` y con otros tenants;
3. en modo simulación no escribe;
4. en modo aplicación ejecuta únicamente `update_many({org_id: {$exists: false}}, {$set: {org_id: "cibercom"}})` por colección;
5. vuelve a reportar los conteos y falla si cambia el total de documentos.

También crea, mediante `upsert`, el registro global y la configuración organizacional de Cibercom si faltan. No toca `_id`, relaciones, contraseñas, archivos ni valores de negocio.

## Aislamiento y autorización

Se mantienen el `before_request` que carga `g.org_id` desde el JWT y el proxy de `tenant_db`. La mejora debe cerrar estas superficies:

- el filtro impuesto debe prevalecer aunque código de negocio envíe otro `org_id`;
- inserts y reemplazos deben imponer el tenant actual, no aceptar uno proporcionado por el cuerpo;
- agregaciones deben comenzar dentro del tenant y evitar etapas capaces de sustituir el conjunto antes del filtro;
- métodos no envueltos que puedan leer o escribir datos requieren wrappers seguros o uso explícito y revisado de `mongo.db.raw`;
- índices de unicidad propios de una empresa deben ser compuestos con `org_id`;
- las rutas globales sólo usan `raw` con autorización del operador de Cibercom o durante registro/migración.

Las pruebas crearán al menos dos tenants y demostrarán que lecturas, actualizaciones, borrados, agregaciones y búsquedas por `_id` no cruzan espacios.

## Nómina como integración preparada

La ruta `/nomina` deja de presentar el calculador ISR/IMSS. El motor y la colección `nomina_parametros` permanecen almacenados para no borrar datos, pero dejan de ser la fuente de esta pantalla.

### Modelo normalizado

El backend devuelve elementos con esta forma estable:

```json
{
  "external_id": "string",
  "employee_id": "string|null",
  "employee_number": "string|null",
  "employee_name": "string|null",
  "period_start": "ISO-8601|null",
  "period_end": "ISO-8601|null",
  "gross": 0,
  "deductions": 0,
  "net": 0,
  "currency": "MXN",
  "status": "pending|paid|cancelled|unknown",
  "paid_at": "ISO-8601|null"
}
```

No se persiste `raw_metadata` ni se devuelve al frontend en esta fase.

### Interfaz del proveedor

El backend define:

```python
class PayrollProvider:
    def list_payrolls(self, filters: dict, tenant: str) -> dict: ...
    def get_payroll(self, external_id: str, tenant: str) -> dict: ...
```

El proveedor inicial `UnconfiguredPayrollProvider` devuelve un estado estructurado `configured: false` sin hacer llamadas de red. La futura integración implementará la misma interfaz y normalizará la respuesta del sistema de facturación.

`GET /payrolls` admite `search`, `employee_id`, `status`, `period_start`, `period_end`, `page` y `page_size`. Su respuesta incluye `configured`, `items`, `page`, `page_size` y `total`. Sólo `SUPER_ADMIN`, `ADMIN` y `CONTADOR` pueden consultar la tabla.

La configuración externa existente se reutiliza y se amplía sólo con campos neutrales: nombre, URL base, esquema de autenticación, API key cifrada, timeout y estado. No se inventan rutas, encabezados adicionales ni mapeos hasta conocer el contrato real.

### Interfaz de usuario

La tabla incluye búsqueda, periodo, empleado, estado, paginación y las columnas: empleado, periodo, percepciones, deducciones, neto, estado y fecha de pago.

Estados obligatorios:

- sin configurar: llamada a configurar la integración, visible para `SUPER_ADMIN`;
- cargando: esqueleto o indicador consistente con el sistema;
- vacío: integración configurada sin resultados;
- error: mensaje recuperable sin datos técnicos ni secretos;
- datos: tabla responsiva con formato monetario y fechas `es-MX`.

## Manejo de errores y seguridad

- Validación server-side de todos los campos públicos.
- Rate limiting del registro en el despliegue o, si no existe infraestructura disponible, un límite de aplicación documentado y testeado.
- Contraseñas nunca se registran ni se almacenan en Mongo cuando Aegis es la autoridad.
- Los errores externos se traducen; cuerpos y credenciales del proveedor no se devuelven al cliente.
- Timeouts obligatorios para Aegis y el futuro proveedor de nómina.
- Auditoría de alta, activación y fallos de aprovisionamiento; auditoría de cambios de integración sin incluir la API key.

## Pruebas y criterios de aceptación

Backend:

- normalización, reserva y colisión de slugs;
- registro exitoso, reintento idempotente y fallo parcial simulado;
- ausencia de contraseñas y secretos en Mongo y respuestas;
- migración en simulación, aplicación y segunda ejecución sin cambios;
- conteos históricos intactos;
- aislamiento entre `cibercom` y otro tenant en todas las operaciones soportadas;
- autorización de catálogo global y tabla de nómina;
- proveedor de nómina no configurado y normalización contractual.

Frontend:

- `/` muestra landing sin sesión y sus CTA navegan correctamente;
- `/registro` valida campos y maneja disponibilidad, éxito y errores;
- `/<slug>` mantiene el login de empresa y un slug inexistente muestra 404;
- `/Login` continúa disponible;
- `/nomina` cubre estados sin configurar, cargando, vacío, error y datos;
- no se renderiza el calculador fiscal anterior.

Verificación manual:

- registrar una empresa de prueba contra un Aegis de desarrollo;
- entrar por su slug y crear datos que no aparecen en Cibercom;
- confirmar que Cibercom conserva sus documentos y acceso;
- confirmar que ninguna API key aparece en red, almacenamiento del navegador o logs.

## Fuera de alcance

- cobros, planes o suscripciones;
- dominios personalizados por empresa;
- importación de empleados durante el registro;
- implementación del proveedor real de facturación sin su contrato;
- eliminación física del calculador o de datos históricos de nómina;
- rediseño general del producto.

