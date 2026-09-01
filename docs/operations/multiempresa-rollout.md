# Despliegue multiempresa

## Condiciones previas

- Mantener `PUBLIC_REGISTRATION_ENABLED=false` hasta conectar y probar el contrato real de creación de tenants en Aegis.
- Crear un respaldo administrado de MongoDB antes del backfill.
- Guardar `JWT_SECRET_KEY`, `MONGO_URI`, `AEGIS_API_KEY` y la clave de cifrado únicamente en el gestor de secretos del host.

## Secuencia

1. Desplegar primero el backend compatible con documentos con y sin `org_id`.
2. Ejecutar `python scripts/backfill_cibercom_tenant.py` sin argumentos y archivar el JSON de simulación.
3. Confirmar que `total` coincide con los conteos esperados y que ningún documento con otro tenant cambiará.
4. Ejecutar `python scripts/backfill_cibercom_tenant.py --apply` una sola vez.
5. Repetir la simulación y confirmar `without_org: 0` en todas las colecciones operativas.
6. Desplegar el frontend.
7. Verificar `/`, `/Login`, `/cibercom`, `/registro` y `/nomina`.
8. Conectar el `TenantProvisioner`, probarlo en un entorno no productivo y sólo entonces activar `PUBLIC_REGISTRATION_ENABLED=true`.

El script nunca elimina documentos ni revierte `org_id`. Una segunda ejecución es idempotente. Desactivar nuevos registros consiste en volver a establecer `PUBLIC_REGISTRATION_ENABLED=false`; las empresas existentes continúan funcionando.

## Nómina

La pantalla consume `GET /payrolls`. Hasta implementar el contrato del sistema de facturación, `UnconfiguredPayrollProvider` devuelve `configured: false`. La configuración externa conserva la API key cifrada y nunca la envía al navegador.
