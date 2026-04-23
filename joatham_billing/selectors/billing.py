from django.db.models import Prefetch, Q

from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise
from joatham_clients.selectors.clients import get_clients_by_entreprise

from ..models import Facture, FactureHistorique, PaiementFacture, Service


def get_facture_queryset():
    return Facture.objects.select_related("client", "entreprise").prefetch_related(
        "lignes",
        Prefetch("paiements", queryset=PaiementFacture.objects.order_by("-date_paiement", "-id")),
        Prefetch("historique", queryset=FactureHistorique.objects.select_related("user").order_by("-created_at", "-id")),
    )


def get_factures_by_entreprise(entreprise, *, client_id=None, statut=None, search=None, date_debut=None, date_fin=None):
    queryset = scope_queryset_to_entreprise(get_facture_queryset(), entreprise)

    if client_id:
        queryset = queryset.filter(client_id=client_id)

    if statut == "paye":
        queryset = queryset.filter(paye=True)
    elif statut == "impaye":
        queryset = queryset.filter(paye=False)
    elif statut in dict(Facture.Statut.choices):
        queryset = queryset.filter(statut=statut)

    if search:
        queryset = queryset.filter(
            Q(client_nom__icontains=search)
            | Q(client__nom__icontains=search)
            | Q(numero__icontains=search)
        )

    if date_debut:
        queryset = queryset.filter(date__date__gte=date_debut)

    if date_fin:
        queryset = queryset.filter(date__date__lte=date_fin)

    return queryset.order_by("-date")


def get_facture_by_entreprise(entreprise, facture_id):
    return get_object_for_entreprise(get_facture_queryset(), entreprise, id=facture_id)


def get_services_by_entreprise(entreprise):
    return scope_queryset_to_entreprise(Service.objects.all(), entreprise).order_by("nom")


def get_service_by_entreprise(entreprise, service_id):
    return get_object_for_entreprise(Service.objects.all(), entreprise, id=service_id)


def get_clients_for_billing_by_entreprise(entreprise):
    return get_clients_by_entreprise(entreprise)


def get_paiements_by_facture_for_entreprise(entreprise, facture):
    if facture.entreprise_id != entreprise.id:
        return PaiementFacture.objects.none()
    return facture.paiements.all()


def get_billing_dashboard_data(entreprise):
    factures = get_factures_by_entreprise(entreprise)
    return {
        "factures": factures,
        "count": factures.count(),
        "payees": factures.filter(paye=True).count(),
        "impayees": factures.filter(paye=False).count(),
    }
