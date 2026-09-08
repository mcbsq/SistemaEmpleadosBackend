# tests/test_leads.py
# ─────────────────────────────────────────────────────────────────────────────
# Solicitudes de información del sitio público (Observaciones Empleados
# 2026-09-03, punto 2): "Crear mi empresa"/"Comenzar ahora" capturan datos y
# avisan por correo a Cibercom — no dan de alta ningún tenant.
import api.leads.logic as leads_logic
from api.leads.logic import crear_lead, CONTACTO_EMAIL


def test_crear_lead_envia_correo_a_contacto_cibercom(monkeypatch):
    enviados = []
    monkeypatch.setattr(leads_logic, "send_generic_email", lambda to, asunto, cuerpo: enviados.append((to, asunto, cuerpo)) or True)

    body, status = crear_lead({
        "nombre": "Ana Pérez", "correo": "ana@example.com",
        "telefono": "5512345678", "notas": "Somos 40 personas.",
    })

    assert status == 201
    assert body == {"ok": True}
    assert len(enviados) == 1
    to, asunto, cuerpo = enviados[0]
    assert to == CONTACTO_EMAIL
    assert "Ana Pérez" in asunto
    assert "ana@example.com" in cuerpo
    assert "5512345678" in cuerpo
    assert "Somos 40 personas." in cuerpo


def test_crear_lead_sin_notas_no_falla(monkeypatch):
    monkeypatch.setattr(leads_logic, "send_generic_email", lambda *a, **k: True)
    body, status = crear_lead({"nombre": "Beto", "correo": "beto@example.com", "telefono": "555"})
    assert status == 201


def test_crear_lead_rechaza_correo_invalido():
    body, status = crear_lead({"nombre": "Ana", "correo": "no-es-un-correo", "telefono": "555"})
    assert status == 400
    assert body["error"] == "invalid_lead"


def test_crear_lead_rechaza_campos_faltantes():
    body, status = crear_lead({"correo": "ana@example.com", "telefono": "555"})
    assert status == 400

    body, status = crear_lead({"nombre": "Ana", "correo": "ana@example.com"})
    assert status == 400


def test_crear_lead_reporta_si_falla_el_envio(monkeypatch):
    monkeypatch.setattr(leads_logic, "send_generic_email", lambda *a, **k: False)
    body, status = crear_lead({"nombre": "Ana", "correo": "ana@example.com", "telefono": "555"})
    assert status == 503
    assert body["error"] == "email_delivery_failed"
