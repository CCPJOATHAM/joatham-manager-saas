from core.models import PaiementAbonnement


def get_subscription_payments_by_entreprise(entreprise):
    return (
        PaiementAbonnement.objects.filter(entreprise=entreprise)
        .select_related("plan", "valide_par")
        .order_by("-date_creation", "-id")
    )


def get_pending_subscription_payments():
    return (
        PaiementAbonnement.objects.filter(statut=PaiementAbonnement.Statut.EN_ATTENTE)
        .select_related("entreprise", "plan", "valide_par")
        .order_by("-date_creation", "-id")
    )


def get_latest_subscription_payment_by_entreprise(entreprise):
    return (
        PaiementAbonnement.objects.filter(entreprise=entreprise)
        .select_related("plan", "valide_par")
        .order_by("-date_creation", "-id")
        .first()
    )


def get_subscription_payment_for_super_admin(paiement_id):
    try:
        return PaiementAbonnement.objects.select_related("entreprise", "plan").get(id=paiement_id)
    except (PaiementAbonnement.DoesNotExist, TypeError, ValueError):
        raise ValueError("Paiement abonnement introuvable.")
