from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from core.api_permissions import BusinessPermissionAPI, IsEntrepriseMemberAPI, ModuleAccessAPI
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_clients.selectors.clients import get_clients_by_entreprise
from joatham_clients.services.clients_service import create_client_for_entreprise

from .serializers import ClientCreateSerializer, ClientSerializer


class ClientViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ClientSerializer
    permission_classes = [IsEntrepriseMemberAPI]

    def get_queryset(self):
        entreprise = get_user_entreprise_or_raise(self.request.user)
        queryset = get_clients_by_entreprise(entreprise)
        search = (self.request.GET.get("q") or "").strip()
        if search:
            queryset = queryset.filter(nom__icontains=search)
        return queryset

    def get_permissions(self):
        if self.action == "create":
            return [
                IsEntrepriseMemberAPI(),
                BusinessPermissionAPI("clients.manage"),
                ModuleAccessAPI("clients"),
            ]
        return [
            IsEntrepriseMemberAPI(),
            BusinessPermissionAPI("clients.view"),
            ModuleAccessAPI("clients"),
        ]

    def create(self, request, *args, **kwargs):
        serializer = ClientCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entreprise = get_user_entreprise_or_raise(request.user)
        client = create_client_for_entreprise(
            entreprise=entreprise,
            nom=serializer.validated_data["nom"],
            telephone=serializer.validated_data.get("telephone", ""),
            email=serializer.validated_data.get("email", ""),
            utilisateur=request.user,
        )
        return Response(ClientSerializer(client).data, status=status.HTTP_201_CREATED)
