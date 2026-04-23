from django.db.models import Count, Q

from joatham_users.models import AbonnementEntreprise, Entreprise


def get_super_admin_entreprise_queryset(*, search=None, statut=None):
    queryset = (
        Entreprise.objects.all()
        .select_related("abonnement_entreprise__plan")
        .annotate(user_count=Count("user"))
    )

    if search:
        queryset = queryset.filter(Q(nom__icontains=search) | Q(raison_sociale__icontains=search))

    if statut:
        queryset = queryset.filter(abonnement_entreprise__statut=statut)

    return queryset.order_by("nom", "id")


def get_super_admin_subscription_counts():
    subscriptions = AbonnementEntreprise.objects.all()
    return {
        "total_entreprises": Entreprise.objects.count(),
        "essai": subscriptions.filter(statut=AbonnementEntreprise.Statut.ESSAI).count(),
        "actif": subscriptions.filter(statut=AbonnementEntreprise.Statut.ACTIF).count(),
        "expire": subscriptions.filter(statut=AbonnementEntreprise.Statut.EXPIRE).count(),
        "suspendu": subscriptions.filter(statut=AbonnementEntreprise.Statut.SUSPENDU).count(),
        "revenu_estime_futur": 0,
    }
