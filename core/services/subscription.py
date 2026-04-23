from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone

from core.audit import record_audit_event
from core.models import PaiementAbonnement
from core.selectors.subscriptions import get_subscription_with_plan_for_entreprise
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.models import Abonnement, AbonnementEntreprise


SUBSCRIPTION_PAYMENT_DURATIONS = {
    PaiementAbonnement.Duree.MENSUEL: {"label": "Mensuel", "days": 30, "multiplier": Decimal("1")},
    PaiementAbonnement.Duree.TRIMESTRIEL: {"label": "Trimestriel", "days": 90, "multiplier": Decimal("3")},
    PaiementAbonnement.Duree.ANNUEL: {"label": "Annuel", "days": 365, "multiplier": Decimal("12")},
}


def get_current_subscription(entreprise):
    if entreprise is None:
        return None
    return getattr(entreprise, "abonnement_entreprise", None)


def get_subscription_for_entreprise(entreprise):
    subscription = get_subscription_with_plan_for_entreprise(entreprise)
    if subscription is not None:
        return subscription
    return get_current_subscription(entreprise)


def get_or_create_default_trial_plan():
    plan = Abonnement.objects.filter(actif=True).order_by("prix", "id").first()
    if plan:
        return plan
    return Abonnement.objects.create(
        nom="Essai JOATHAM",
        code="trial-default",
        prix=0,
        duree_jours=14,
        actif=True,
        description="Plan d'essai automatique pour l'onboarding SaaS.",
    )


def is_subscription_expired(subscription, *, as_of=None):
    if subscription is None or not subscription.date_fin:
        return True
    as_of = as_of or timezone.localdate()
    return subscription.date_fin < as_of


def has_active_subscription_access(entreprise, *, as_of=None):
    return is_subscription_active(entreprise, as_of=as_of, allow_trial=True)


def is_subscription_active(entreprise, *, as_of=None, allow_trial=True):
    subscription = get_subscription_for_entreprise(entreprise)
    if subscription is None or not subscription.actif:
        return False

    refresh_subscription_status(entreprise, as_of=as_of)
    subscription.refresh_from_db()
    allowed_statuses = {AbonnementEntreprise.Statut.ACTIF}
    if allow_trial:
        allowed_statuses.add(AbonnementEntreprise.Statut.ESSAI)

    return subscription.statut in allowed_statuses and not is_subscription_expired(subscription, as_of=as_of)


def activate_subscription_for_entreprise(*, entreprise, plan, utilisateur=None, date_debut=None, duration_days=None, prolong_existing=False):
    date_debut = date_debut or timezone.localdate()
    days = duration_days or plan.duree_jours
    current_subscription = get_current_subscription(entreprise)
    start_for_end = date_debut
    if prolong_existing and current_subscription and current_subscription.date_fin and current_subscription.date_fin >= date_debut:
        start_for_end = current_subscription.date_fin
    date_fin = start_for_end + timedelta(days=days)
    subscription, _ = AbonnementEntreprise.objects.update_or_create(
        entreprise=entreprise,
        defaults={
            "plan": plan,
            "statut": AbonnementEntreprise.Statut.ACTIF,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "essai": False,
            "actif": True,
        },
    )
    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="abonnement_active",
        module="subscription",
        objet_type="AbonnementEntreprise",
        objet_id=subscription.id,
        description=f"Abonnement active sur le plan {plan.nom}.",
        metadata={"plan_id": plan.id, "plan_nom": plan.nom, "statut": subscription.statut},
    )
    return subscription


def get_subscription_payment_duration_options():
    return SUBSCRIPTION_PAYMENT_DURATIONS


def calculate_subscription_payment_amount(*, plan, duree):
    duration = SUBSCRIPTION_PAYMENT_DURATIONS.get(duree)
    if duration is None:
        raise ValueError("Duree d'abonnement invalide.")
    return Decimal(str(plan.prix)) * duration["multiplier"]


def get_subscription_payment_duration_days(duree):
    duration = SUBSCRIPTION_PAYMENT_DURATIONS.get(duree)
    if duration is None:
        raise ValueError("Duree d'abonnement invalide.")
    return duration["days"]


@transaction.atomic
def create_subscription_payment_request(*, entreprise, plan, duree, reference_paiement, preuve_paiement=None, utilisateur=None):
    montant = calculate_subscription_payment_amount(plan=plan, duree=duree)
    paiement = PaiementAbonnement.objects.create(
        entreprise=entreprise,
        plan=plan,
        duree=duree,
        montant=montant,
        reference_paiement=(reference_paiement or "").strip(),
        preuve_paiement=preuve_paiement,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="paiement_abonnement_cree",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Demande de paiement abonnement creee pour le plan {plan.nom}.",
        metadata={"plan_id": plan.id, "duree": duree, "montant": str(montant)},
    )
    return paiement


@transaction.atomic
def validate_subscription_payment(*, paiement, super_admin):
    if paiement.statut != PaiementAbonnement.Statut.EN_ATTENTE:
        raise ValueError("Seuls les paiements en attente peuvent etre valides.")
    duration_days = get_subscription_payment_duration_days(paiement.duree)
    subscription = activate_subscription_for_entreprise(
        entreprise=paiement.entreprise,
        plan=paiement.plan,
        utilisateur=super_admin,
        duration_days=duration_days,
        prolong_existing=True,
    )
    paiement.statut = PaiementAbonnement.Statut.VALIDE
    paiement.date_validation = timezone.now()
    paiement.valide_par = super_admin
    paiement.save(update_fields=["statut", "date_validation", "valide_par"])
    record_audit_event(
        entreprise=paiement.entreprise,
        utilisateur=super_admin,
        action="paiement_abonnement_valide",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Paiement abonnement valide pour le plan {paiement.plan.nom}.",
        metadata={"plan_id": paiement.plan_id, "montant": str(paiement.montant), "subscription_id": subscription.id},
    )
    return subscription


@transaction.atomic
def refuse_subscription_payment(*, paiement, super_admin):
    if paiement.statut != PaiementAbonnement.Statut.EN_ATTENTE:
        raise ValueError("Seuls les paiements en attente peuvent etre refuses.")
    paiement.statut = PaiementAbonnement.Statut.REFUSE
    paiement.date_validation = timezone.now()
    paiement.valide_par = super_admin
    paiement.save(update_fields=["statut", "date_validation", "valide_par"])
    record_audit_event(
        entreprise=paiement.entreprise,
        utilisateur=super_admin,
        action="paiement_abonnement_refuse",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Paiement abonnement refuse pour le plan {paiement.plan.nom}.",
        metadata={"plan_id": paiement.plan_id, "montant": str(paiement.montant)},
    )
    return paiement


def start_trial_for_entreprise(*, entreprise, plan, utilisateur=None, date_debut=None, trial_days=None):
    date_debut = date_debut or timezone.localdate()
    duration = trial_days or plan.duree_jours
    date_fin = date_debut + timedelta(days=duration)
    subscription, _ = AbonnementEntreprise.objects.update_or_create(
        entreprise=entreprise,
        defaults={
            "plan": plan,
            "statut": AbonnementEntreprise.Statut.ESSAI,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "essai": True,
            "actif": True,
        },
    )
    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="essai_demarre",
        module="subscription",
        objet_type="AbonnementEntreprise",
        objet_id=subscription.id,
        description=f"Essai demarre sur le plan {plan.nom}.",
        metadata={"plan_id": plan.id, "plan_nom": plan.nom, "statut": subscription.statut},
    )
    return subscription


def suspend_subscription_for_entreprise(*, entreprise, utilisateur=None):
    subscription = get_current_subscription(entreprise)
    if subscription is None:
        return None
    subscription.statut = AbonnementEntreprise.Statut.SUSPENDU
    subscription.actif = False
    subscription.save(update_fields=["statut", "actif"])
    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="abonnement_suspendu",
        module="subscription",
        objet_type="AbonnementEntreprise",
        objet_id=subscription.id,
        description=f"Abonnement suspendu pour le plan {subscription.plan.nom}.",
        metadata={"plan_id": subscription.plan_id, "plan_nom": subscription.plan.nom, "statut": subscription.statut},
    )
    return subscription


def refresh_subscription_status(entreprise, *, as_of=None, utilisateur=None):
    subscription = get_current_subscription(entreprise)
    if subscription is None:
        return None
    as_of = as_of or timezone.localdate()
    if subscription.statut in {
        AbonnementEntreprise.Statut.ACTIF,
        AbonnementEntreprise.Statut.ESSAI,
    } and is_subscription_expired(subscription, as_of=as_of):
        subscription.statut = AbonnementEntreprise.Statut.EXPIRE
        subscription.actif = False
        subscription.save(update_fields=["statut", "actif"])
        _sync_legacy_entreprise_subscription_fields(entreprise, subscription)
        record_audit_event(
            entreprise=entreprise,
            utilisateur=utilisateur,
            action="abonnement_expire",
            module="subscription",
            objet_type="AbonnementEntreprise",
            objet_id=subscription.id,
            description=f"Abonnement expire pour le plan {subscription.plan.nom}.",
            metadata={"plan_id": subscription.plan_id, "plan_nom": subscription.plan.nom, "statut": subscription.statut},
        )
    return subscription


def subscription_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        entreprise = get_user_entreprise_or_raise(request.user)
        if not has_active_subscription_access(entreprise):
            return redirect("abonnement_expire")
        return view_func(request, *args, **kwargs)

    return wrapped


def _sync_legacy_entreprise_subscription_fields(entreprise, subscription):
    entreprise.abonnement = subscription.plan if subscription else None
    entreprise.date_expiration = subscription.date_fin if subscription else None
    entreprise.save(update_fields=["abonnement", "date_expiration"])


def sync_legacy_entreprise_subscription_fields(entreprise, subscription):
    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)
