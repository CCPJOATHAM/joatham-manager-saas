from rest_framework import viewsets

from core.api_permissions import BusinessPermissionAPI, IsEntrepriseMemberAPI, ModuleAccessAPI
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_depenses.services.depenses_service import list_depenses_for_entreprise

from .serializers import DepenseSerializer


class DepenseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DepenseSerializer
    permission_classes = [IsEntrepriseMemberAPI]

    def get_queryset(self):
        entreprise = get_user_entreprise_or_raise(self.request.user)
        return list_depenses_for_entreprise(
            entreprise,
            date_debut=self.request.GET.get("date_debut"),
            date_fin=self.request.GET.get("date_fin"),
            recherche=self.request.GET.get("q"),
        )

    def get_permissions(self):
        return [
            IsEntrepriseMemberAPI(),
            BusinessPermissionAPI("expenses.view"),
            ModuleAccessAPI("expenses"),
        ]
