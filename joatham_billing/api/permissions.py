from core.api_permissions import BusinessPermissionAPI, IsEntrepriseMemberAPI, ModuleAccessAPI


class IsEntrepriseMember(IsEntrepriseMemberAPI):
    pass


class CanManageFacturesAPI(BusinessPermissionAPI):
    permission_code = "billing.manage"


class CanRecordPaymentAPI(BusinessPermissionAPI):
    permission_code = "billing.payments"


class CanViewFacturesAPI(BusinessPermissionAPI):
    permission_code = "billing.view"


class CanAccessBillingModuleAPI(ModuleAccessAPI):
    module_name = "billing"
