class PayrollProvider:
    def list_payrolls(self, filters, tenant):
        raise NotImplementedError

    def get_payroll(self, external_id, tenant):
        raise NotImplementedError


class UnconfiguredPayrollProvider(PayrollProvider):
    def list_payrolls(self, filters, tenant):
        return {"configured": False, "items": [], "page": filters["page"], "page_size": filters["page_size"], "total": 0}

    def get_payroll(self, external_id, tenant):
        return {"configured": False, "item": None}
