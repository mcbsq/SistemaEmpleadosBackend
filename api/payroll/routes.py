from api.auth_decorators import require_roles
from .logic import list_payrolls


def setup_payroll_routes(app, mongo):
    @app.route('/payrolls', methods=['GET'])
    @require_roles('SUPER_ADMIN', 'ADMIN', 'CONTADOR')
    def list_payrolls_route():
        return list_payrolls(app)
