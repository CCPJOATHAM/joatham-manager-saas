from core.models import Abonnement


def get_subscription_with_plan_for_entreprise(entreprise):
    if entreprise is None:
        return None
    return (
        Abonnement.objects.select_related("plan", "entreprise")
        .filter(entreprise=entreprise)
        .first()
    )
