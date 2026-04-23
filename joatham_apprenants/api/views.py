from rest_framework import viewsets

from core.api_permissions import BusinessPermissionAPI, IsEntrepriseMemberAPI, ModuleAccessAPI
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_apprenants.selectors.apprenants import (
    get_apprenants_by_entreprise,
    get_filtered_inscriptions_by_entreprise,
    get_formations_by_entreprise,
)

from .serializers import ApprenantSerializer, FormationSerializer, InscriptionSerializer


class ApprenantViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApprenantSerializer
    permission_classes = [IsEntrepriseMemberAPI]

    def get_queryset(self):
        entreprise = get_user_entreprise_or_raise(self.request.user)
        queryset = get_apprenants_by_entreprise(entreprise)
        actif = (self.request.GET.get("actif") or "").strip().lower()
        if actif in {"true", "1"}:
            queryset = queryset.filter(actif=True)
        elif actif in {"false", "0"}:
            queryset = queryset.filter(actif=False)
        return queryset

    def get_permissions(self):
        return [
            IsEntrepriseMemberAPI(),
            BusinessPermissionAPI("apprenants.view"),
            ModuleAccessAPI("apprenants"),
        ]


class FormationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FormationSerializer
    permission_classes = [IsEntrepriseMemberAPI]

    def get_queryset(self):
        entreprise = get_user_entreprise_or_raise(self.request.user)
        queryset = get_formations_by_entreprise(entreprise)
        actif = (self.request.GET.get("actif") or "").strip().lower()
        if actif in {"true", "1"}:
            queryset = queryset.filter(actif=True)
        elif actif in {"false", "0"}:
            queryset = queryset.filter(actif=False)
        return queryset

    def get_permissions(self):
        return [
            IsEntrepriseMemberAPI(),
            BusinessPermissionAPI("apprenants.view"),
            ModuleAccessAPI("apprenants"),
        ]


class InscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InscriptionSerializer
    permission_classes = [IsEntrepriseMemberAPI]

    def get_queryset(self):
        entreprise = get_user_entreprise_or_raise(self.request.user)
        return get_filtered_inscriptions_by_entreprise(
            entreprise,
            formation_id=(self.request.GET.get("formation") or "").strip() or None,
            statut=(self.request.GET.get("statut") or "").strip() or None,
            apprenant_id=(self.request.GET.get("apprenant") or "").strip() or None,
        )

    def get_permissions(self):
        return [
            IsEntrepriseMemberAPI(),
            BusinessPermissionAPI("apprenants.view"),
            ModuleAccessAPI("apprenants"),
        ]
