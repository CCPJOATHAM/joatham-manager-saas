from core.models import PaiementAbonnement


SUBSCRIPTION_PAYMENT_LIST_FIELDS = (
    "id",
    "entreprise",
    "plan",
    "duree",
    "montant",
    "montant_usd",
    "devise_entreprise",
    "montant_devise_locale_estime",
    "statut",
    "reference_paiement",
    "preuve_paiement",
    "date_creation",
    "date_validation",
    "source_taux",
    "methode_paiement",
    "valide_par",
)

SUBSCRIPTION_PAYMENT_RELATED_DISPLAY_FIELDS = (
    "entreprise__nom",
    "entreprise__raison_sociale",
    "entreprise__devise",
    "plan__nom",
    "valide_par__username",
)


def get_subscription_payments_by_entreprise(entreprise):
    return (
        PaiementAbonnement.objects.filter(entreprise=entreprise)
        .select_related("plan", "valide_par")
        .only(*SUBSCRIPTION_PAYMENT_LIST_FIELDS, *SUBSCRIPTION_PAYMENT_RELATED_DISPLAY_FIELDS)
        .order_by("-date_creation", "-id")
    )


def get_pending_subscription_payments():
    return (
        PaiementAbonnement.objects.filter(statut=PaiementAbonnement.Statut.EN_ATTENTE)
        .exclude(source_taux="demande_plan")
        .select_related("entreprise", "plan", "valide_par")
        .only(*SUBSCRIPTION_PAYMENT_LIST_FIELDS, *SUBSCRIPTION_PAYMENT_RELATED_DISPLAY_FIELDS)
        .order_by("-date_creation", "-id")
    )


def get_latest_subscription_payment_by_entreprise(entreprise):
    return (
        PaiementAbonnement.objects.filter(entreprise=entreprise)
        .select_related("plan", "valide_par")
        .only(*SUBSCRIPTION_PAYMENT_LIST_FIELDS, *SUBSCRIPTION_PAYMENT_RELATED_DISPLAY_FIELDS)
        .order_by("-date_creation", "-id")
        .first()
    )


def get_subscription_payment_for_super_admin(paiement_id):
    try:
        return PaiementAbonnement.objects.select_related("entreprise", "plan").get(id=paiement_id)
    except (PaiementAbonnement.DoesNotExist, TypeError, ValueError):
        raise ValueError("Paiement abonnement introuvable.")
