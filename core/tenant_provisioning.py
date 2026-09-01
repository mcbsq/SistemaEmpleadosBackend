class IdentityProviderUnavailable(RuntimeError):
    pass


class TenantProvisioner:
    def provision(self, *, company_name, slug, admin_name, admin_email, password):
        raise NotImplementedError


class UnavailableTenantProvisioner(TenantProvisioner):
    def provision(self, **_data):
        raise IdentityProviderUnavailable("Aprovisionamiento de Aegis no configurado")
