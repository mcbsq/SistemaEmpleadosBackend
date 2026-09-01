from flask import g, jsonify, request

from core.payroll_provider import UnconfiguredPayrollProvider


ALLOWED_STATUSES = {"pending", "paid", "cancelled", "unknown"}
FIELDS = {"external_id", "employee_id", "employee_number", "employee_name", "period_start", "period_end", "gross", "deductions", "net", "currency", "status", "paid_at"}


def list_payrolls(app):
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("page_size", 25))))
    except ValueError:
        return jsonify({"error": "invalid_pagination"}), 400
    status = request.args.get("status", "")
    if status and status not in ALLOWED_STATUSES:
        return jsonify({"error": "invalid_status"}), 400
    filters = {"page": page, "page_size": page_size, "status": status, "search": request.args.get("search", ""), "employee_id": request.args.get("employee_id", ""), "period_start": request.args.get("period_start", ""), "period_end": request.args.get("period_end", "")}
    provider = app.config.get("PAYROLL_PROVIDER") or UnconfiguredPayrollProvider()
    result = provider.list_payrolls(filters, g.org_id)
    result["items"] = [{key: value for key, value in item.items() if key in FIELDS} for item in result.get("items", [])]
    return jsonify(result), 200
