from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone

from core.audit import record_audit_event
from core.services.subscription import (
    activate_subscription_for_entreprise,
    get_current_subscription,
    refresh_subscription_status,
    start_trial_for_entreprise,
    suspend_subscription_for_entreprise,
    sync_legacy_entreprise_subscription_fields,
)
from joatham_users.models import Abonnement, AbonnementEntreprise, Entreprise


def refresh_all_subscription_statuses(*, utilisateur=None):
    for entreprise in Entreprise.objects.select_related("abonnement_entreprise").all():
        refresh_subscription_status(entreprise, utilisateur=utilisateur)


def get_plan_for_super_admin(plan_id):
    return get_object_or_404(Abonnement.objects.filter(actif=True), id=plan_id)


def get_entreprise_for_super_admin(entreprise_id):
    return get_object_or_404(Entreprise.objects.all(), id=entreprise_id)


def activate_company_subscription(*, entreprise, plan, utilisateur=None):
    return activate_subscription_for_entreprise(
        entreprise=entreprise,
        plan=plan,
        utilisateur=utilisateur,
    )


def suspend_company_subscription(*, entreprise, utilisateur=None):
    return suspend_subscription_for_entreprise(
        entreprise=entreprise,
        utilisateur=utilisateur,
    )


def extend_company_trial(*, entreprise, days, utilisateur=None, plan=None):
    days = int(days or 0)
    if days <= 0:
        raise ValueError("La prolongation d'essai doit etre strictement positive.")

    subscription = get_current_subscription(entreprise)
    today = timezone.localdate()

    if subscription is None:
        selected_plan = plan or Abonnement.objects.filter(actif=True).order_by("prix", "id").first()
        if selected_plan is None:
            raise ValueError("Aucun plan actif n'est disponible pour demarrer un essai.")
        return start_trial_for_entreprise(
            entreprise=entreprise,
            plan=selected_plan,
            utilisateur=utilisateur,
            date_debut=today,
            trial_days=days,
        )

    base_date = subscription.date_fin if subscription.date_fin and subscription.date_fin >= today else today
    subscription.date_fin = base_date + timedelta(days=days)
    subscription.statut = AbonnementEntreprise.Statut.ESSAI
    subscription.essai = True
    subscription.actif = True
    if plan is not None:
        subscription.plan = plan
    if not subscription.date_debut:
        subscription.date_debut = today
    subscription.save(update_fields=["date_fin", "statut", "essai", "actif", "plan", "date_debut"])
    sync_legacy_entreprise_subscription_fields(entreprise, subscription)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="essai_prolonge",
        module="super_admin",
        objet_type="AbonnementEntreprise",
        objet_id=subscription.id,
        description=f"Essai prolonge de {days} jour(s) pour {entreprise.nom}.",
        metadata={"days": days, "plan_id": subscription.plan_id, "plan_nom": subscription.plan.nom},
    )
    return subscription


def change_company_plan(*, entreprise, plan, utilisateur=None):
    subscription = get_current_subscription(entreprise)
    if subscription is None:
        return activate_subscription_for_entreprise(
            entreprise=entreprise,
            plan=plan,
            utilisateur=utilisateur,
        )

    subscription.plan = plan
    subscription.save(update_fields=["plan"])
    sync_legacy_entreprise_subscription_fields(entreprise, subscription)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="abonnement_plan_modifie",
        module="super_admin",
        objet_type="AbonnementEntreprise",
        objet_id=subscription.id,
        description=f"Plan modifie vers {plan.nom} pour {entreprise.nom}.",
        metadata={"plan_id": plan.id, "plan_nom": plan.nom, "statut": subscription.statut},
    )
    return subscription
