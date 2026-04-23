from decimal import Decimal

from django.db.models import Count, DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from core.models import PaiementAbonnement
from joatham_users.models import AbonnementEntreprise, Entreprise, User


def get_super_admin_entreprise_queryset(*, search=None, statut=None):
    owner_users = User.objects.filter(
        entreprise=OuterRef("pk"),
        role=User.Role.PROPRIETAIRE,
    ).order_by("id")
    latest_payment = PaiementAbonnement.objects.filter(entreprise=OuterRef("pk")).order_by("-date_creation", "-id")

    queryset = (
        Entreprise.objects.all()
        .select_related("abonnement_entreprise__plan")
        .annotate(
            owner_email=Coalesce(Subquery(owner_users.values("email")[:1]), Value("")),
            owner_username=Coalesce(Subquery(owner_users.values("username")[:1]), Value("")),
            last_payment_amount=Subquery(latest_payment.values("montant")[:1]),
            last_payment_status=Subquery(latest_payment.values("statut")[:1]),
            last_payment_created_at=Subquery(latest_payment.values("date_creation")[:1]),
            payment_request_count=Count("paiements_abonnement"),
        )
    )

    if search:
        queryset = queryset.filter(
            Q(nom__icontains=search)
            | Q(raison_sociale__icontains=search)
            | Q(email__icontains=search)
            | Q(user__email__icontains=search, user__role=User.Role.PROPRIETAIRE)
        ).distinct()

    if statut:
        queryset = queryset.filter(abonnement_entreprise__statut=statut)

    return queryset.order_by("nom", "id")


def get_super_admin_subscription_counts():
    subscriptions = AbonnementEntreprise.objects.all()
    payments = PaiementAbonnement.objects.all()
    return {
        "total_accounts": Entreprise.objects.count(),
        "essai": subscriptions.filter(statut=AbonnementEntreprise.Statut.ESSAI).count(),
        "actif": subscriptions.filter(statut=AbonnementEntreprise.Statut.ACTIF).count(),
        "expire": subscriptions.filter(statut=AbonnementEntreprise.Statut.EXPIRE).count(),
        "suspendu": subscriptions.filter(statut=AbonnementEntreprise.Statut.SUSPENDU).count(),
        "pending_payments": payments.filter(statut=PaiementAbonnement.Statut.EN_ATTENTE).count(),
        "validated_revenue": payments.filter(statut=PaiementAbonnement.Statut.VALIDE).aggregate(
            total=Coalesce(Sum("montant"), Value(Decimal("0.00")), output_field=DecimalField(max_digits=12, decimal_places=2))
        )["total"],
    }
