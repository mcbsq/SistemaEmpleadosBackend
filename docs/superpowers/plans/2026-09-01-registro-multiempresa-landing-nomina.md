# Registro multiempresa, landing y nómina Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publicar una landing coherente con CibercomHR, permitir el registro autoservicio preparado para Aegis, preservar los datos históricos bajo `cibercom` y reemplazar el calculador visible de nómina por una tabla conectable a un proveedor futuro.

**Architecture:** Flask conserva MongoDB compartido detrás de `BaseDatosMultiTenant`; los endpoints públicos delegan el alta de identidad a una interfaz de aprovisionamiento inyectable y sólo activan el tenant tras completar Mongo y Aegis. React separa las superficies públicas de la aplicación autenticada. Nómina se consume mediante una interfaz de proveedor normalizada cuyo adaptador inicial informa que aún no está configurado.

**Tech Stack:** React 18/Create React App, React Router 6, Flask 2.3, PyMongo 4, Flask-JWT-Extended, pytest, React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-01-registro-multiempresa-landing-nomina-design.md`

## Global Constraints

- Los ZIP del directorio padre no se modifican.
- Todo dato histórico sin `org_id` se asigna a `cibercom`; ningún documento se elimina ni sobrescribe si ya tiene tenant.
- El slug histórico definitivo es `cibercom`.
- `/Login` continúa funcionando.
- La UI reutiliza `src/styles/design-tokens.css` y los patrones existentes; no se agrega un framework visual.
- No se inventa el contrato HTTP de Aegis ni el del sistema de facturación.
- En producción, el registro responde `identity_provider_unavailable` hasta conectar un `AegisProvisioner` real; las pruebas usan un fake explícito.
- API keys y contraseñas no aparecen en respuestas, logs ni almacenamiento del navegador.

---

## File Map

### Backend

- `core/tenant_db.py`: imponer siempre el tenant de la request.
- `scripts/backfill_cibercom_tenant.py`: migración idempotente con simulación y reporte.
- `core/tenant_provisioning.py`: interfaz y proveedor Aegis no configurado.
- `api/tenants/registration.py`: validación, reserva y orquestación del alta.
- `api/tenants/routes.py`: endpoints públicos y listado administrativo existente.
- `core/payroll_provider.py`: contrato normalizado de nómina.
- `api/payroll/logic.py`, `api/payroll/routes.py`: tabla paginada protegida.
- `app.py`: registrar nuevas rutas.
- `tests/fakes.py`: soporte de índices/operaciones requeridos por nuevas pruebas.

### Frontend

- `src/pages/PublicLanding.jsx`, `src/pages/PublicLanding.css`: landing.
- `src/pages/CompanyRegistration.jsx`, `src/pages/CompanyRegistration.css`: alta autoservicio.
- `src/services/registrationService.js`: API pública.
- `src/Components/PayrollTable.jsx`, `src/Components/NominaConfig.css`: tabla y estados.
- `src/services/payrollService.js`: filtros paginados.
- `src/App.js`: rutas públicas y sustitución del componente de nómina.

---

### Task 1: Blindar la capa multiempresa

**Files:**
- Modify: `core/tenant_db.py`
- Modify: `tests/fakes.py`
- Create: `tests/test_tenant_db.py`

**Interfaces:**
- Consumes: `flask.g.org_id` establecido por `app.cargar_org_id`.
- Produces: `BaseDatosMultiTenant` que impone el tenant actual en filtros, documentos, reemplazos y upserts.

- [ ] **Step 1: Escribir pruebas fallidas de imposición de tenant**

```python
# tests/test_tenant_db.py
from flask import Flask, g
from tests.fakes import FakeMongo
from core.tenant_db import BaseDatosMultiTenant

def test_filtro_no_puede_sustituir_tenant_actual():
    app = Flask(__name__)
    raw = FakeMongo().db
    db = BaseDatosMultiTenant(raw)
    raw.empleados.insert_one({"Nombre": "A", "org_id": "empresa-a"})
    raw.empleados.insert_one({"Nombre": "B", "org_id": "empresa-b"})
    with app.test_request_context():
        g.org_id = "empresa-a"
        assert db.empleados.find_one({"org_id": "empresa-b"}) is None

def test_insert_y_replace_imponen_tenant_actual():
    app = Flask(__name__)
    raw = FakeMongo().db
    db = BaseDatosMultiTenant(raw)
    with app.test_request_context():
        g.org_id = "empresa-a"
        result = db.empleados.insert_one({"Nombre": "A", "org_id": "empresa-b"})
        db.empleados.replace_one({"_id": result.inserted_id}, {"Nombre": "Actualizado", "org_id": "empresa-b"})
    assert raw.empleados.find_one({"_id": result.inserted_id})["org_id"] == "empresa-a"

def test_upsert_impone_tenant_actual_en_filtro_y_documento():
    app = Flask(__name__)
    raw = FakeMongo().db
    db = BaseDatosMultiTenant(raw)
    with app.test_request_context():
        g.org_id = "empresa-a"
        db.organizacion.update_one(
            {"org_id": "empresa-b"},
            {"$set": {"name": "A"}, "$setOnInsert": {"org_id": "empresa-b"}},
            upsert=True,
        )
    assert raw.organizacion.find_one({"org_id": "empresa-a"})["name"] == "A"
    assert raw.organizacion.find_one({"org_id": "empresa-b"}) is None
```

- [ ] **Step 2: Ejecutar las pruebas y confirmar el fallo**

Run: `pytest tests/test_tenant_db.py -q`

Expected: las consultas o escrituras que proporcionan `empresa-b` escapan del tenant actual.

- [ ] **Step 3: Imponer el tenant en vez de usar `setdefault`**

```python
# core/tenant_db.py
def _filtro(self, filtro):
    org_id = _org_id_actual()
    filtro = dict(filtro) if filtro else {}
    if org_id is not None:
        filtro["org_id"] = org_id
    return filtro

def _doc_con_org(self, documento):
    documento = dict(documento) if documento else {}
    org_id = _org_id_actual()
    if org_id is not None:
        documento["org_id"] = org_id
    return documento

def _update_con_org_en_upsert(self, update, kwargs):
    if kwargs.get("upsert") and isinstance(update, dict) and any(str(k).startswith("$") for k in update):
        org_id = _org_id_actual()
        if org_id is not None:
            update = dict(update)
            set_on_insert = dict(update.get("$setOnInsert", {}))
            set_on_insert["org_id"] = org_id
            update["$setOnInsert"] = set_on_insert
    return update
```

Actualizar `tests/fakes.py` sólo si `replace_one` o `upsert` no emulan las operaciones utilizadas, manteniendo la misma semántica que PyMongo.

- [ ] **Step 4: Ejecutar pruebas unitarias e integración multiempresa**

Run: `pytest tests/test_tenant_db.py tests/test_integracion_multiempresa.py -q`

Expected: PASS; la prueba de integración puede omitirse únicamente si faltan `MONGO_URI`/`JWT_SECRET_KEY`, reportando el motivo.

- [ ] **Step 5: Commit**

```bash
git add core/tenant_db.py tests/fakes.py tests/test_tenant_db.py
git commit -m "fix: enforce tenant ownership in database proxy"
```

### Task 2: Migración idempotente de datos históricos a Cibercom

**Files:**
- Create: `scripts/backfill_cibercom_tenant.py`
- Create: `tests/test_backfill_cibercom_tenant.py`

**Interfaces:**
- Consumes: una base PyMongo sin proxy y `target_org_id="cibercom"`.
- Produces: `build_report(db, collections)` y `backfill(db, collections, target_org_id, apply=False)`.

- [ ] **Step 1: Escribir pruebas de simulación, aplicación y segunda ejecución**

```python
# tests/test_backfill_cibercom_tenant.py
from tests.fakes import FakeMongo
from scripts.backfill_cibercom_tenant import backfill

def test_dry_run_no_escribe_y_reporta():
    db = FakeMongo().db
    db.empleados.insert_one({"Nombre": "Histórico"})
    report = backfill(db, ["empleados"], "cibercom", apply=False)
    assert report["empleados"]["before"]["without_org"] == 1
    assert db.empleados.find_one({"Nombre": "Histórico"}).get("org_id") is None

def test_aplica_solo_a_documentos_sin_org_y_es_idempotente():
    db = FakeMongo().db
    db.empleados.insert_one({"Nombre": "Histórico"})
    db.empleados.insert_one({"Nombre": "Otro", "org_id": "otra"})
    first = backfill(db, ["empleados"], "cibercom", apply=True)
    second = backfill(db, ["empleados"], "cibercom", apply=True)
    assert first["empleados"]["updated"] == 1
    assert second["empleados"]["updated"] == 0
    assert db.empleados.count_documents({}) == 2
    assert db.empleados.find_one({"Nombre": "Otro"})["org_id"] == "otra"

def test_aplicacion_crea_catalogo_y_config_de_cibercom_sin_duplicar():
    db = FakeMongo().db
    backfill(db, ["empleados"], "cibercom", apply=True)
    backfill(db, ["empleados"], "cibercom", apply=True)
    assert db.tenants.count_documents({"org_id": "cibercom"}) == 1
    assert db.organizacion.count_documents({"org_id": "cibercom"}) == 1
```

- [ ] **Step 2: Confirmar el fallo**

Run: `pytest tests/test_backfill_cibercom_tenant.py -q`

Expected: FAIL por módulo inexistente.

- [ ] **Step 3: Implementar reporte y backfill sin borrados**

El script define la lista explícita de colecciones operativas actuales y ejecuta únicamente:

```python
result = collection.update_many(
    {"org_id": {"$exists": False}},
    {"$set": {"org_id": target_org_id}},
)
```

Antes y después calcula `total`, `without_org`, `target_org` y `other_org`. Si el total cambia, lanza `RuntimeError`. En modo aplicación también hace `upsert` idempotente de `tenants` y `organizacion` para `cibercom`, usando `setOnInsert` y sin reemplazar branding existente. El CLI exige `--apply`; sin esa opción siempre es simulación y emite JSON. Carga `MONGO_URI` y `MONGO_DB_NAME` desde entorno, sin valores secretos por defecto.

- [ ] **Step 4: Ejecutar pruebas y simulación local**

Run: `pytest tests/test_backfill_cibercom_tenant.py -q`

Run: `python scripts/backfill_cibercom_tenant.py`

Expected: PASS y reporte JSON; cero escrituras sin `--apply`.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_cibercom_tenant.py tests/test_backfill_cibercom_tenant.py
git commit -m "feat: add safe cibercom tenant backfill"
```

### Task 3: Contrato backend de registro autoservicio

**Files:**
- Create: `core/tenant_provisioning.py`
- Create: `core/public_rate_limit.py`
- Create: `api/tenants/registration.py`
- Modify: `api/tenants/routes.py`
- Create: `tests/test_tenant_registration.py`

**Interfaces:**
- Produces: `normalize_slug(value) -> str`.
- Produces: `TenantProvisioner.provision(company_name, slug, admin_name, admin_email, password) -> ProvisionedIdentity`.
- Produces: `UnavailableTenantProvisioner` que lanza `IdentityProviderUnavailable`.
- Produces: `register_tenant(mongo, payload, provisioner) -> (Response, status)`.
- Produces: `RegistrationRateLimiter.allow(client_key) -> bool`, con ventana y máximo configurables.

- [ ] **Step 1: Escribir pruebas de slugs, disponibilidad y aprovisionamiento**

```python
# tests/test_tenant_registration.py
from tests.fakes import FakeMongo
from api.tenants.registration import normalize_slug, register_tenant

class FakeProvisioner:
    def __init__(self): self.calls = []
    def provision(self, **data):
        self.calls.append(data)
        return {"tenant_id": data["slug"], "user_id": "aegis-user-1"}

def test_normaliza_slug_y_rechaza_reservados():
    assert normalize_slug("  Mi Compañía  ") == "mi-compania"

def test_registro_crea_tenant_config_y_superadmin_sin_guardar_password(app_context):
    mongo = FakeMongo()
    provider = FakeProvisioner()
    response, status = register_tenant(mongo, {
        "company_name": "Mi Compañía", "slug": "mi-compania",
        "admin_name": "Ana Pérez", "admin_email": "ana@ejemplo.com",
        "password": "una-clave-segura-123",
    }, provider)
    assert status == 201
    assert mongo.db.raw.tenants.find_one({"org_id": "mi-compania"})["estado"] == "active"
    admin = mongo.db.raw.usuario.find_one({"org_id": "mi-compania"})
    assert admin["role"] == "SUPER_ADMIN"
    assert "password" not in admin
    assert "una-clave-segura-123" not in str(mongo.db.raw._collections)

def test_reintento_activo_no_duplica(app_context):
    mongo = FakeMongo()
    provider = FakeProvisioner()
    payload = {
        "company_name": "Mi Compañía", "slug": "mi-compania",
        "admin_name": "Ana Pérez", "admin_email": "ana@ejemplo.com",
        "password": "una-clave-segura-123",
    }
    assert register_tenant(mongo, payload, provider)[1] == 201
    assert register_tenant(mongo, payload, provider)[1] == 200
    assert mongo.db.raw.tenants.count_documents({"org_id": "mi-compania"}) == 1
    assert mongo.db.raw.usuario.count_documents({"org_id": "mi-compania"}) == 1
    assert len(provider.calls) == 1

def test_rate_limiter_bloquea_despues_del_limite():
    limiter = RegistrationRateLimiter(max_attempts=2, window_seconds=60)
    assert limiter.allow("198.51.100.10") is True
    assert limiter.allow("198.51.100.10") is True
    assert limiter.allow("198.51.100.10") is False
```

- [ ] **Step 2: Ejecutar las pruebas y confirmar el fallo**

Run: `pytest tests/test_tenant_registration.py -q`

Expected: FAIL por módulos inexistentes.

- [ ] **Step 3: Implementar validación y proveedor no configurado**

```python
# core/tenant_provisioning.py
class IdentityProviderUnavailable(RuntimeError):
    pass

class TenantProvisioner:
    def provision(self, *, company_name, slug, admin_name, admin_email, password):
        raise NotImplementedError

class UnavailableTenantProvisioner(TenantProvisioner):
    def provision(self, **_data):
        raise IdentityProviderUnavailable("Aprovisionamiento de Aegis no configurado")
```

`registration.py` valida email, contraseña mínima de 12 caracteres, campos obligatorios, slug de 3–63 caracteres y reservados. Usa `mongo.db.raw.tenant_provisioning` para reserva idempotente. Nunca incluye `password` en documentos ni logs. Tras un fake exitoso inserta/upserta `organizacion`, `usuario` y `tenants`, marcando el intento `active`. En error externo marca `failed` con un código, no con el cuerpo sensible.

`public_rate_limit.py` mantiene, bajo `threading.Lock`, marcas de tiempo por clave de cliente, purga entradas fuera de ventana y limita por defecto a 5 intentos por hora. La ruta usa `request.remote_addr`; el proxy de producción debe sobrescribirlo sólo desde encabezados confiables. `PUBLIC_REGISTRATION_ENABLED=false` responde 503 sin llamar al provisioner.

- [ ] **Step 4: Exponer endpoints públicos con provisioner inyectable**

```python
# api/tenants/routes.py
@app.route('/public/tenants/slug-availability', methods=['GET'])
def slug_availability_route():
    return slug_availability(mongo, request.args.get("slug", ""))

@app.route('/public/tenants/register', methods=['POST'])
def register_tenant_route():
    if not app.config.get("PUBLIC_REGISTRATION_ENABLED", False):
        return jsonify({"error": "registration_disabled"}), 503
    limiter = app.config["REGISTRATION_RATE_LIMITER"]
    if not limiter.allow(request.remote_addr or "unknown"):
        return jsonify({"error": "rate_limited"}), 429
    return register_tenant(
        mongo,
        request.get_json(silent=True) or {},
        app.config.get("TENANT_PROVISIONER") or UnavailableTenantProvisioner(),
    )
```

- [ ] **Step 5: Ejecutar pruebas del módulo y seguridad**

Run: `pytest tests/test_tenant_registration.py tests/test_integracion_multiempresa.py -q`

Expected: PASS; sin proveedor configurado, la ruta real devuelve HTTP 503 con `identity_provider_unavailable` y no crea un tenant activo.

- [ ] **Step 6: Commit**

```bash
git add core/tenant_provisioning.py core/public_rate_limit.py api/tenants/registration.py api/tenants/routes.py tests/test_tenant_registration.py
git commit -m "feat: add idempotent company registration contract"
```

### Task 4: Landing y formulario público

**Files:**
- Create: `src/pages/PublicLanding.jsx`
- Create: `src/pages/PublicLanding.css`
- Create: `src/pages/CompanyRegistration.jsx`
- Create: `src/pages/CompanyRegistration.css`
- Create: `src/services/registrationService.js`
- Create: `src/pages/PublicLanding.test.jsx`
- Create: `src/pages/CompanyRegistration.test.jsx`
- Modify: `src/App.js`

**Interfaces:**
- Consumes: `GET /public/tenants/slug-availability` y `POST /public/tenants/register`.
- Produces: `/`, `/registro` y navegación a `/<slug>` tras éxito.

- [ ] **Step 1: Escribir pruebas fallidas de rutas y validación**

```jsx
// src/pages/PublicLanding.test.jsx
render(<MemoryRouter><PublicLanding /></MemoryRouter>);
expect(screen.getByRole("heading", { name: /gestiona a tu equipo/i })).toBeInTheDocument();
expect(screen.getByRole("link", { name: /crear mi empresa/i })).toHaveAttribute("href", "/registro");

// src/pages/CompanyRegistration.test.jsx
render(<MemoryRouter><CompanyRegistration /></MemoryRouter>);
await user.click(screen.getByRole("button", { name: /crear empresa/i }));
expect(screen.getByText(/completa el nombre de la empresa/i)).toBeInTheDocument();
```

- [ ] **Step 2: Confirmar el fallo**

Run: `CI=true npm test -- --watchAll=false --runInBand PublicLanding.test.jsx CompanyRegistration.test.jsx`

Expected: FAIL por componentes inexistentes.

- [ ] **Step 3: Implementar el servicio público**

```javascript
// src/services/registrationService.js
import { apiFetch } from "./apiConfig";
export const registrationService = {
  availability: slug => apiFetch(`/public/tenants/slug-availability?slug=${encodeURIComponent(slug)}`),
  register: payload => apiFetch("/public/tenants/register", {
    method: "POST", body: JSON.stringify(payload),
  }),
};
```

- [ ] **Step 4: Implementar landing con contenido comprobable**

Crear hero, capacidades existentes, bloque de funcionamiento y CTA final. Usar clases propias apoyadas en variables `--hr-*`. No añadir cifras, testimonios, planes o imágenes externas. Encabezado: “CibercomHR”; título: “Gestiona a tu equipo desde un solo lugar”; CTA primario: “Crear mi empresa”; secundario: “Ya tengo una cuenta”.

- [ ] **Step 5: Implementar registro y estados**

El formulario mantiene un único objeto `form`, genera el slug a partir del nombre mientras el usuario no lo edite, consulta disponibilidad tras 400 ms, valida correo/contraseña/confirmación y muestra errores de API por campo o globales. En éxito navega a `data.login_url`.

- [ ] **Step 6: Integrar rutas sin romper `/<slug>`**

En `App.js`, agregar `registro` a `RESERVED_ROOT_SEGMENTS`, renderizar `PublicLanding` cuando `location.pathname === "/"`, `CompanyRegistration` en `/registro`, y conservar `OrgGate` para otros segmentos únicos y `/Login` para login genérico.

- [ ] **Step 7: Ejecutar pruebas y build**

Run: `CI=true npm test -- --watchAll=false --runInBand PublicLanding.test.jsx CompanyRegistration.test.jsx`

Run: `npm run build`

Expected: PASS y build sin errores.

- [ ] **Step 8: Commit frontend**

```bash
git add src/App.js src/pages src/services/registrationService.js
git commit -m "feat: add public landing and company registration"
```

### Task 5: Contrato backend de consulta de nómina

**Files:**
- Create: `core/payroll_provider.py`
- Create: `api/payroll/__init__.py`
- Create: `api/payroll/logic.py`
- Create: `api/payroll/routes.py`
- Modify: `app.py`
- Create: `tests/test_payroll_api.py`

**Interfaces:**
- Produces: `PayrollProvider.list_payrolls(filters, tenant)` y `.get_payroll(external_id, tenant)`.
- Produces: `GET /payrolls` para `SUPER_ADMIN`, `ADMIN` y `CONTADOR`.

- [ ] **Step 1: Escribir pruebas del proveedor no configurado, filtros y autorización**

```python
# tests/test_payroll_api.py
def test_unconfigured_provider_returns_empty_contract(client, jwt_admin):
    response = client.get("/payrolls", headers={"Authorization": f"Bearer {jwt_admin}"})
    assert response.status_code == 200
    assert response.get_json() == {
        "configured": False, "items": [], "page": 1, "page_size": 25, "total": 0
    }

def test_employee_cannot_list_company_payroll(client, jwt_employee):
    assert client.get("/payrolls", headers={"Authorization": f"Bearer {jwt_employee}"}).status_code == 403

def test_provider_receives_tenant_and_normalized_filters(client, jwt_admin, fake_provider):
    client.application.config["PAYROLL_PROVIDER"] = fake_provider
    response = client.get(
        "/payrolls?status=paid&page=2&page_size=10",
        headers={"Authorization": f"Bearer {jwt_admin}"},
    )
    assert response.status_code == 200
    assert fake_provider.last_tenant == "empresa-a"
    assert fake_provider.last_filters["status"] == "paid"
```

- [ ] **Step 2: Confirmar el fallo**

Run: `pytest tests/test_payroll_api.py -q`

Expected: FAIL por ruta inexistente.

- [ ] **Step 3: Implementar interfaz y normalizador**

```python
# core/payroll_provider.py
class PayrollProvider:
    def list_payrolls(self, filters: dict, tenant: str) -> dict:
        raise NotImplementedError
    def get_payroll(self, external_id: str, tenant: str) -> dict:
        raise NotImplementedError

class UnconfiguredPayrollProvider(PayrollProvider):
    def list_payrolls(self, filters, tenant):
        return {"configured": False, "items": [], "page": filters["page"],
                "page_size": filters["page_size"], "total": 0}
```

`logic.py` limita `page_size` a 100, valida estado y fechas, toma `g.org_id` y devuelve sólo los campos normalizados de la especificación. Descarta claves desconocidas del proveedor.

- [ ] **Step 4: Registrar ruta protegida**

`routes.py` usa `@require_roles('SUPER_ADMIN', 'ADMIN', 'CONTADOR')`. `app.py` importa y ejecuta `setup_payroll_routes(app, mongo)`. No se borran `api/nomina` ni `nomina_parametros`.

- [ ] **Step 5: Ejecutar pruebas**

Run: `pytest tests/test_payroll_api.py tests/test_conexiones_externas.py -q`

Expected: PASS y conservación de cifrado/configuración externa existente.

- [ ] **Step 6: Commit**

```bash
git add core/payroll_provider.py api/payroll app.py tests/test_payroll_api.py
git commit -m "feat: add provider-neutral payroll query API"
```

### Task 6: Sustituir la UI de cálculo por tabla de nómina

**Files:**
- Create: `src/services/payrollService.js`
- Create: `src/Components/PayrollTable.jsx`
- Create: `src/Components/PayrollTable.test.jsx`
- Modify: `src/Components/NominaConfig.css`
- Modify: `src/App.js`

**Interfaces:**
- Consumes: `GET /payrolls`.
- Produces: tabla con estados no configurado, carga, vacío, error y datos.

- [ ] **Step 1: Escribir pruebas de los cinco estados**

```jsx
// src/Components/PayrollTable.test.jsx
it("muestra integración pendiente", async () => {
  payrollService.list.mockResolvedValue({ configured: false, items: [], page: 1, page_size: 25, total: 0 });
  render(<PayrollTable />);
  expect(await screen.findByText(/integración de nómina aún no está configurada/i)).toBeInTheDocument();
});

it("renderiza una nómina normalizada", async () => {
  payrollService.list.mockResolvedValue({ configured: true, items: [{
    external_id: "n1", employee_name: "Ana Pérez", period_start: "2026-08-01",
    period_end: "2026-08-15", gross: 10000, deductions: 2000, net: 8000,
    currency: "MXN", status: "paid", paid_at: "2026-08-15T12:00:00Z",
  }], page: 1, page_size: 25, total: 1 });
  render(<PayrollTable />);
  expect(await screen.findByText("Ana Pérez")).toBeInTheDocument();
  expect(screen.getByText(/8,000/)).toBeInTheDocument();
});
```

Agregar casos equivalentes para `loading`, `configured: true/items: []` y promesa rechazada.

- [ ] **Step 2: Confirmar el fallo**

Run: `CI=true npm test -- --watchAll=false --runInBand PayrollTable.test.jsx`

Expected: FAIL por componentes inexistentes.

- [ ] **Step 3: Implementar servicio y serialización de filtros**

```javascript
// src/services/payrollService.js
import { apiFetch } from "./apiConfig";
export const payrollService = {
  list(filters = {}) {
    const query = new URLSearchParams(
      Object.entries(filters).filter(([, value]) => value !== "" && value != null)
    );
    return apiFetch(`/payrolls?${query.toString()}`);
  },
};
```

- [ ] **Step 4: Implementar tabla y accesibilidad**

`PayrollTable` mantiene filtros y paginación, cancela actualizaciones de efectos desmontados, formatea moneda con `Intl.NumberFormat("es-MX", {style:"currency", currency})`, usa encabezados `<th scope="col">`, etiqueta estados y ofrece “Configurar integración” a `/integraciones` sólo para `SUPER_ADMIN`.

- [ ] **Step 5: Sustituir componente en rutas**

En `App.js`, importar `PayrollTable` y usarlo en `<Route path="/nomina">`. Dejar `NominaConfig.jsx` y endpoints antiguos almacenados, pero sin navegación ni renderizado.

- [ ] **Step 6: Ejecutar pruebas y build**

Run: `CI=true npm test -- --watchAll=false --runInBand PayrollTable.test.jsx`

Run: `npm run build`

Expected: PASS; ninguna cadena “Motor de nómina”, “Tabla ISR” o “Calcular” aparece en `/nomina`.

- [ ] **Step 7: Commit frontend**

```bash
git add src/App.js src/Components/PayrollTable.jsx src/Components/PayrollTable.test.jsx src/Components/NominaConfig.css src/services/payrollService.js
git commit -m "feat: replace payroll calculator with query table"
```

### Task 7: Verificación integral y documentación operativa

**Files:**
- Create: `docs/operations/multiempresa-rollout.md`
- Modify: `.env.example` (crear si no existe)

**Interfaces:**
- Documenta: simulación/aplicación del backfill, variables requeridas, rollback lógico y conexión futura de proveedores.

- [ ] **Step 1: Documentar despliegue sin secretos**

Incluir este orden exacto:

1. respaldo de MongoDB administrado por el proveedor;
2. desplegar código compatible con documentos sin `org_id`;
3. ejecutar `python scripts/backfill_cibercom_tenant.py` y archivar reporte;
4. revisar conteos;
5. ejecutar con `--apply` una sola vez;
6. ejecutar nuevamente en simulación y confirmar `without_org: 0`;
7. desplegar frontend;
8. probar `/`, `/Login`, `/cibercom`, `/registro` y `/nomina`.

Documentar que no existe rollback destructivo: el campo `org_id` agregado se conserva. Para desactivar registro se deja `TENANT_PROVISIONER` sin configurar o se usa `PUBLIC_REGISTRATION_ENABLED=false`.

- [ ] **Step 2: Añadir variables públicas de ejemplo**

```dotenv
PUBLIC_REGISTRATION_ENABLED=false
MONGO_DB_NAME=controlempleados
# AEGIS provisioning se habilita únicamente al implementar su contrato real.
```

No incluir valores para `MONGO_URI`, `JWT_SECRET_KEY`, `AEGIS_API_KEY` ni claves de cifrado.

- [ ] **Step 3: Ejecutar suite backend completa**

Run: `pytest -q`

Expected: PASS; las pruebas de integración que requieran servicios reales deben indicar explícitamente SKIP, no fallar por credenciales ausentes.

- [ ] **Step 4: Ejecutar suite frontend y build**

Run: `CI=true npm test -- --watchAll=false --runInBand`

Run: `npm run build`

Expected: PASS.

- [ ] **Step 5: Revisar diferencias y secretos**

Run en ambos repositorios: `git diff --check`

Run: `rg -n '(mongodb\+srv://|JWT_SECRET_KEY\s*=|AEGIS_API_KEY\s*=|api_key\s*[:=]\s*["'"'][^"'"']+)' --glob '!node_modules/**' --glob '!build/**' --glob '!venv/**'`

Expected: sin espacios inválidos ni secretos nuevos; las referencias de documentación no contienen valores.

- [ ] **Step 6: Commit backend de documentación**

```bash
git add docs/operations/multiempresa-rollout.md .env.example
git commit -m "docs: add safe multiempresa rollout guide"
```

- [ ] **Step 7: Inspección manual final**

Levantar backend y frontend locales con variables de prueba. Confirmar:

- `/` conserva la estética actual;
- `/registro` valida y, sin provisioner, muestra un error recuperable sin activar tenant;
- `/cibercom` carga el login existente;
- `/Login` sigue disponible;
- dos JWT de tenants distintos no pueden leer el mismo `_id`;
- `/nomina` muestra integración pendiente y enlaza a configuración;
- la API key nunca aparece en DevTools Network ni sessionStorage.
