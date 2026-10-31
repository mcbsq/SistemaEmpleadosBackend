# tests/conftest.py
# Las pruebas nunca mandan correos reales: app.py carga .env.local, y con
# RESEND_API_KEY ahí cualquier aviso (vacaciones, altas…) saldría por Resend.
import pytest


@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
