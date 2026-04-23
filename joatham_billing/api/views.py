from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.services.tenancy import get_user_entreprise_or_raise
from joatham_billing.exceptions import FacturationError
from joatham_billing.selectors.billing import get_factures_by_entreprise
from joatham_billing.services.facturation import (
    change_facture_status,
    create_facture,
    register_payment,
)

from .permissions import CanManageFacturesAPI, CanRecordPaymentAPI, IsEntrepriseMember
from .permissions import CanAccessBillingModuleAPI, CanViewFacturesAPI
from .serializers import (
    FactureCreateSerializer,
    FacturePaymentSerializer,
    FactureSerializer,
    FactureStatusSerializer,
)


class FactureViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FactureSerializer
    permission_classes = [IsEntrepriseMember]

    def get_queryset(self):
        entreprise = get_user_entreprise_or_raise(self.request.user)
        return get_factures_by_entreprise(
            entreprise,
            client_id=self.request.GET.get("client"),
            statut=self.request.GET.get("statut"),
            search=self.request.GET.get("search"),
            date_debut=self.request.GET.get("date_debut") or None,
            date_fin=self.request.GET.get("date_fin") or None,
        )

    def get_permissions(self):
        if self.action in {"create_facture", "changer_statut"}:
            return [IsEntrepriseMember(), CanManageFacturesAPI(), CanAccessBillingModuleAPI()]
        if self.action == "enregistrer_paiement":
            return [IsEntrepriseMember(), CanRecordPaymentAPI(), CanAccessBillingModuleAPI()]
        return [IsEntrepriseMember(), CanViewFacturesAPI(), CanAccessBillingModuleAPI()]

    @action(detail=False, methods=["post"], url_path="create")
    def create_facture(self, request):
        serializer = FactureCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entreprise = get_user_entreprise_or_raise(request.user)
        try:
            facture = create_facture(
                entreprise=entreprise,
                user=request.user,
                client_id=serializer.validated_data.get("client"),
                client_nom=serializer.validated_data.get("client_nom", ""),
                tva=serializer.validated_data.get("tva", 0),
                remise=serializer.validated_data.get("remise", 0),
                rabais=serializer.validated_data.get("rabais", 0),
                ristourne=serializer.validated_data.get("ristourne", 0),
                lignes=serializer.validated_data["lignes"],
            )
        except FacturationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(FactureSerializer(facture).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="status")
    def changer_statut(self, request, pk=None):
        facture = self.get_object()
        serializer = FactureStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            change_facture_status(
                facture=facture,
                nouveau_statut=serializer.validated_data["statut"],
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except FacturationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        facture.refresh_from_db()
        return Response(FactureSerializer(facture).data)

    @action(detail=True, methods=["post"], url_path="payments")
    def enregistrer_paiement(self, request, pk=None):
        facture = self.get_object()
        serializer = FacturePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            paiement = register_payment(
                facture=facture,
                montant=serializer.validated_data["montant"],
                mode=serializer.validated_data["mode"],
                reference=serializer.validated_data.get("reference", ""),
                note=serializer.validated_data.get("note", ""),
                user=request.user,
            )
        except FacturationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": paiement.id, "detail": "Paiement enregistre."}, status=status.HTTP_201_CREATED)
