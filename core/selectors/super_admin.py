from decimal import Decimal

from django.db.models import Count, DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from core.models import PaiementAbonnement
from joatham_users.models import AbonnementEntreprise, Entreprise, User


def get_super_admin_entreprise_queryset(*, search=None, statut=None, include_inactive=False):
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
            last_payment_id=Subquery(latest_payment.values("id")[:1]),
            last_payment_plan_name=Subquery(latest_payment.values("plan__nom")[:1]),
            last_payment_reference=Subquery(latest_payment.values("reference_paiement")[:1]),
            last_payment_amount_usd=Subquery(latest_payment.values("montant_usd")[:1]),
            last_payment_currency=Subquery(latest_payment.values("devise_entreprise")[:1]),
            last_payment_local_amount=Subquery(latest_payment.values("montant_devise_locale_estime")[:1]),
            last_payment_status=Subquery(latest_payment.values("statut")[:1]),
            last_payment_source=Subquery(latest_payment.values("source_taux")[:1]),
            last_payment_created_at=Subquery(latest_payment.values("date_creation")[:1]),
            payment_request_count=Count("paiements_abonnement"),
        )
    )

    if not include_inactive:
        queryset = queryset.filter(is_active=True)

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
    subscriptions = AbonnementEntreprise.objects.filter(entreprise__is_active=True)
    payments = PaiementAbonnement.objects.filter(entreprise__is_active=True)
    active_entreprises = Entreprise.objects.filter(is_active=True)
    total_accounts = active_entreprises.count()
    return {
        "total_accounts": total_accounts,
        "total_entreprises": total_accounts,
        "inactive_entreprises": Entreprise.objects.filter(is_active=False).count(),
        "essai": subscriptions.filter(statut=AbonnementEntreprise.Statut.ESSAI).count(),
        "actif": subscriptions.filter(statut=AbonnementEntreprise.Statut.ACTIF).count(),
        "expire": subscriptions.filter(statut=AbonnementEntreprise.Statut.EXPIRE).count(),
        "suspendu": subscriptions.filter(statut=AbonnementEntreprise.Statut.SUSPENDU).count(),
        "pending_payments": payments.filter(statut=PaiementAbonnement.Statut.EN_ATTENTE).count(),
        "validated_revenue": payments.filter(statut=PaiementAbonnement.Statut.VALIDE).aggregate(
            total=Coalesce(Sum("montant_usd"), Value(Decimal("0.00")), output_field=DecimalField(max_digits=12, decimal_places=2))
        )["total"],
    }
