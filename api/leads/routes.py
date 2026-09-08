# api/leads/routes.py
from flask import jsonify, request

from .logic import crear_lead
from core.public_rate_limit import RegistrationRateLimiter

# Instancia propia — independiente del limitador de /public/tenants/register,
# para que un abuso de un endpoint no consuma la cuota del otro.
_LEAD_RATE_LIMITER = RegistrationRateLimiter(max_attempts=5, window_seconds=3600)


def setup_leads_routes(app):

    @app.route('/public/leads', methods=['POST'])
    def crear_lead_route():
        if not _LEAD_RATE_LIMITER.allow(request.remote_addr or "unknown"):
            return jsonify({"error": "rate_limited"}), 429
        body, status = crear_lead(request.get_json(silent=True) or {})
        return jsonify(body), status
