from rest_framework.permissions import BasePermission

from core.services.product_policy import can_access_module
from joatham_users.permissions import user_has_permission


class IsEntrepriseMemberAPI(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.entreprise_id)


class BusinessPermissionAPI(BasePermission):
    permission_code = None

    def __init__(self, permission_code=None):
        if permission_code:
            self.permission_code = permission_code

    def has_permission(self, request, view):
        if not self.permission_code:
            return False
        return user_has_permission(request.user, self.permission_code)


class ModuleAccessAPI(BasePermission):
    module_name = None

    def __init__(self, module_name=None):
        if module_name:
            self.module_name = module_name

    def has_permission(self, request, view):
        if not self.module_name:
            return False
        return can_access_module(request.user, self.module_name)
