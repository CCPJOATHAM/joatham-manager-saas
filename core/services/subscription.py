import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps

from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone

from core.audit import record_audit_event
from core.models import PaiementAbonnement, PlatformSettings
from core.selectors.subscriptions import get_subscription_with_plan_for_entreprise
from core.services.currency import get_currency_code
from core.services.exchange_rates import (
    ExchangeRateUnavailable,
    convert_amount,
    get_company_currency,
    get_plan_price_for_company,
    get_platform_currency,
)
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.models import Abonnement, AbonnementEntreprise


DEFAULT_WHATSAPP_NUMBER = "243970258117"
DEFAULT_WHATSAPP_MESSAGE = "Je veux payer mon abonnement JOATHAM Pro"
FREE_PLAN_CODE = "free"
STARTER_PLAN_CODE = "starter"
PRO_PLAN_CODE = "pro"
PREMIUM_PLAN_CODE = "premium"
BUSINESS_PLAN_CODE = "business"
OFFICIAL_COMMERCIAL_PLAN_CODES = (
    FREE_PLAN_CODE,
    STARTER_PLAN_CODE,
    PRO_PLAN_CODE,
    PREMIUM_PLAN_CODE,
)
OFFICIAL_PAID_PLAN_CODES = (
    STARTER_PLAN_CODE,
    PRO_PLAN_CODE,
    PREMIUM_PLAN_CODE,
)
LEGACY_TRIAL_PLAN_CODES = ("trial-default", "trial_default", "trial")
FREE_PLAN_DURATION_DAYS = 365 * 100
FREE_PLAN_INVOICE_LIMIT = 20
FREE_PLAN_USER_LIMIT = 1
FREE_PLAN_CLIENT_LIMIT = 50
FREE_PLAN_MODULES = [
    "dashboard",
    "clients",
    "services",
    "expenses",
    "depenses",
    "caisse",
    "products",
    "produits",
    "billing",
    "factures",
    "subscription",
    "abonnements",
]
STARTER_PLAN_MODULES = [
    "dashboard",
    "clients",
    "services",
    "expenses",
    "depenses",
    "caisse",
    "products",
    "produits",
    "billing",
    "factures",
    "subscription",
    "abonnements",
]
PRO_PLAN_MODULES = STARTER_PLAN_MODULES + [
    "stock",
    "stock_reports",
    "stock_exports",
    "inventory",
    "inventaire",
    "caisse_reports",
    "caisse_exports",
    "caisse_integrations",
    "caisse_validation",
    "users",
    "utilisateurs",
]
PREMIUM_PLAN_MODULES = PRO_PLAN_MODULES + [
    "accounting",
    "comptabilite",
    "accounting_reports",
    "accounting_exports",
    "audit",
    "audit_advanced",
    "messages",
    "apprenants",
]
PLAN_CODE_ALIASES = {
    "gratuit": FREE_PLAN_CODE,
    "decouverte": FREE_PLAN_CODE,
    "starter": STARTER_PLAN_CODE,
    "pro": PRO_PLAN_CODE,
    "premium": PREMIUM_PLAN_CODE,
    "business": PREMIUM_PLAN_CODE,
    "premium_business": PREMIUM_PLAN_CODE,
}
PLAN_QUOTA_PROFILES = {
    FREE_PLAN_CODE: {
        "max_produits": 30,
        "max_depenses_mois": 20,
        "max_caisses": 1,
    },
    STARTER_PLAN_CODE: {
        "max_produits": 300,
        "max_depenses_mois": 100,
        "max_caisses": 1,
    },
    PRO_PLAN_CODE: {
        "max_produits": 3000,
        "max_depenses_mois": 1000,
        "max_caisses": 5,
    },
    PREMIUM_PLAN_CODE: {
        "max_produits": None,
        "max_depenses_mois": None,
        "max_caisses": None,
    },
}
UNLIMITED_QUOTA_PROFILE = {
    "max_produits": None,
    "max_depenses_mois": None,
    "max_caisses": None,
}
DEFAULT_PAID_PLANS = [
    {
        "code": STARTER_PLAN_CODE,
        "nom": "Starter",
        "prix": 19,
        "prix_annuel": Decimal("190.00"),
        "devise": "USD",
        "duree_jours": 30,
        "description": "Facturation, clients, produits, depenses et caisse simple pour une petite activite.",
        "modules_inclus": STARTER_PLAN_MODULES,
        "max_utilisateurs": 3,
        "max_factures_mois": 100,
        "max_clients": 300,
        "max_apprenants": 0,
        "acces_comptabilite": False,
        "acces_exports": True,
    },
    {
        "code": PRO_PLAN_CODE,
        "nom": "Pro",
        "prix": 49,
        "prix_annuel": Decimal("490.00"),
        "devise": "USD",
        "duree_jours": 30,
        "description": "Gestion complete avec caisse avancee, stock, inventaire, rapports et exports.",
        "modules_inclus": PRO_PLAN_MODULES,
        "max_utilisateurs": 10,
        "max_factures_mois": 1000,
        "max_clients": 3000,
        "max_apprenants": 0,
        "acces_comptabilite": False,
        "acces_exports": True,
    },
    {
        "code": PREMIUM_PLAN_CODE,
        "nom": "Premium / Business",
        "prix": 99,
        "prix_annuel": Decimal("990.00"),
        "devise": "USD",
        "duree_jours": 30,
        "description": "Tous les modules actuels, comptabilite avancee, audit, rapports financiers et capacites etendues.",
        "modules_inclus": PREMIUM_PLAN_MODULES,
        "max_utilisateurs": None,
        "max_factures_mois": None,
        "max_clients": None,
        "max_apprenants": None,
        "acces_comptabilite": True,
        "acces_exports": True,
    },
]
PLAN_FEATURE_SUMMARY = {
    FREE_PLAN_CODE: [
        "Acces decouverte avec dashboard simple",
        "Clients, produits, depenses et factures limites",
        "Une caisse active pour tester les flux de base",
        "Stock avance, inventaire, rapports avances et exports avances non inclus",
    ],
    STARTER_PLAN_CODE: [
        "Facturation plus confortable",
        "Clients, produits et depenses pour une petite equipe",
        "Caisse simple avec une caisse active",
        "Rapports de base et exports simples",
    ],
    PRO_PLAN_CODE: [
        "Tout Starter",
        "Stock avance, mouvements et inventaire physique",
        "Rapports stock, caisse complete et exports Excel/PDF",
        "Paiements facture et depenses rattaches a la caisse",
        "Utilisateurs multiples et roles metier",
    ],
    PREMIUM_PLAN_CODE: [
        "Tout Pro",
        "Comptabilite avancee et rapports financiers",
        "Audit avance, messagerie et tous les modules actuels",
        "Utilisateurs, clients, produits et factures sans limite applicative",
        "Support prioritaire et options futures",
    ],
}
SUBSCRIPTION_PAYMENT_DURATIONS = {
    PaiementAbonnement.Duree.MENSUEL: {"label": "Mensuel", "days": 30, "multiplier": Decimal("1")},
    PaiementAbonnement.Duree.TRIMESTRIEL: {"label": "Trimestriel", "days": 90, "multiplier": Decimal("3")},
    PaiementAbonnement.Duree.SEMESTRIEL: {"label": "Semestriel", "days": 180, "multiplier": Decimal("6")},
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


def is_free_plan(plan):
    return normalize_plan_code(plan) == FREE_PLAN_CODE


def is_official_commercial_plan(plan):
    return normalize_plan_code(plan) in OFFICIAL_COMMERCIAL_PLAN_CODES


def normalize_plan_code(plan_or_code):
    raw_code = getattr(plan_or_code, "code", plan_or_code)
    code = (raw_code or "").strip().lower().replace("-", "_").replace("/", "_").replace(" ", "_")
    if not code and hasattr(plan_or_code, "nom"):
        code = (getattr(plan_or_code, "nom", "") or "").strip().lower().replace("-", "_").replace("/", "_").replace(" ", "_")
    code = unicodedata.normalize("NFKD", code).encode("ascii", "ignore").decode("ascii")
    while "__" in code:
        code = code.replace("__", "_")
    code = code.strip("_")
    return PLAN_CODE_ALIASES.get(code, code)


def get_plan_quota_profile(plan):
    return {**UNLIMITED_QUOTA_PROFILE, **PLAN_QUOTA_PROFILES.get(normalize_plan_code(plan), {})}


def get_plan_feature_summary(plan):
    return PLAN_FEATURE_SUMMARY.get(normalize_plan_code(plan), [])


def get_default_paid_plans():
    return DEFAULT_PAID_PLANS


def get_commercial_plans_queryset(*, include_free=True, paid_only=False):
    plan_codes = OFFICIAL_COMMERCIAL_PLAN_CODES if include_free else OFFICIAL_PAID_PLAN_CODES
    queryset = Abonnement.objects.filter(actif=True, code__in=plan_codes)
    if paid_only:
        queryset = queryset.filter(prix__gt=0)
    return queryset


def deactivate_legacy_trial_plans():
    legacy_filter = Q()
    for code in LEGACY_TRIAL_PLAN_CODES:
        legacy_filter |= Q(code__iexact=code)
    for name in ("Essai", "Plan d'essai", "Trial", "Trial default"):
        legacy_filter |= Q(nom__iexact=name)

    official_codes = set(OFFICIAL_COMMERCIAL_PLAN_CODES)
    deactivated = 0
    for plan in Abonnement.objects.filter(legacy_filter).order_by("id"):
        if normalize_plan_code(plan) in official_codes:
            continue

        update_fields = []
        if plan.actif:
            plan.actif = False
            update_fields.append("actif")
        legacy_note = "Plan legacy inactif conserve uniquement pour les anciens abonnements historiques."
        if legacy_note not in (plan.description or ""):
            plan.description = f"{plan.description}\n{legacy_note}".strip()
            update_fields.append("description")
        if update_fields:
            plan.save(update_fields=update_fields)
            deactivated += 1
    return deactivated


def is_entreprise_on_free_plan(entreprise):
    subscription = get_subscription_for_entreprise(entreprise)
    return bool(subscription and is_free_plan(getattr(subscription, "plan", None)))


def get_or_create_free_plan():
    defaults = {
        "nom": "Gratuit",
        "prix": 0,
        "prix_annuel": Decimal("0.00"),
        "devise": get_platform_currency(),
        "duree_jours": FREE_PLAN_DURATION_DAYS,
        "actif": True,
        "description": "Plan gratuit actif pour demarrer JOATHAM Manager avec des limites fortes.",
        "modules_inclus": FREE_PLAN_MODULES,
        "max_utilisateurs": FREE_PLAN_USER_LIMIT,
        "max_factures_mois": FREE_PLAN_INVOICE_LIMIT,
        "max_clients": FREE_PLAN_CLIENT_LIMIT,
        "max_apprenants": 0,
        "acces_comptabilite": False,
        "acces_exports": False,
    }

    plan = Abonnement.objects.filter(code=FREE_PLAN_CODE).order_by("id").first()
    if plan:
        changed_fields = []
        for field, value in defaults.items():
            if getattr(plan, field) != value:
                setattr(plan, field, value)
                changed_fields.append(field)
        if changed_fields:
            plan.save(update_fields=changed_fields)
        return plan

    plan = Abonnement.objects.filter(nom__iexact="Gratuit").order_by("id").first()
    if plan:
        for field, value in {**defaults, "code": FREE_PLAN_CODE}.items():
            setattr(plan, field, value)
        plan.save(update_fields=["code", *defaults.keys()])
        return plan

    return Abonnement.objects.create(code=FREE_PLAN_CODE, **defaults)


def get_or_create_default_free_plan():
    return get_or_create_free_plan()


def get_or_create_default_trial_plan():
    return get_or_create_free_plan()


def get_default_trial_days():
    try:
        return PlatformSettings.get_solo().duree_essai_jours or 14
    except Exception:
        return 14


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


def get_subscription_price_usd(*, plan, duree):
    duration = SUBSCRIPTION_PAYMENT_DURATIONS.get(duree)
    if duration is None:
        raise ValueError("Duree d'abonnement invalide.")
    return Decimal(str(plan.prix)) * duration["multiplier"]


def calculate_subscription_payment_amount(*, plan, duree):
    return get_subscription_price_usd(plan=plan, duree=duree)


def get_subscription_payment_duration_days(duree):
    duration = SUBSCRIPTION_PAYMENT_DURATIONS.get(duree)
    if duration is None:
        raise ValueError("Duree d'abonnement invalide.")
    return duration["days"]


def build_subscription_payment_estimate(*, entreprise, plan, duree):
    amount_usd = get_subscription_price_usd(plan=plan, duree=duree).quantize(Decimal("0.01"))
    try:
        conversion = convert_amount(amount_usd, get_platform_currency(), get_company_currency(entreprise))
        return {
            "plan_id": plan.id,
            "plan_name": plan.nom,
            "period": duree,
            "amount_usd": amount_usd,
            "currency_code": conversion.target_currency,
            "estimated_amount": conversion.amount,
            "exchange_rate": conversion.rate,
            "exchange_source": conversion.provider,
            "exchange_rate_date": conversion.rate_date,
        }
    except ExchangeRateUnavailable:
        return {
            "plan_id": plan.id,
            "plan_name": plan.nom,
            "period": duree,
            "amount_usd": amount_usd,
            "currency_code": get_company_currency(entreprise),
            "estimated_amount": None,
            "exchange_rate": None,
            "exchange_source": "unavailable",
            "exchange_rate_date": None,
        }


def build_subscription_pricing_matrix(*, entreprise, plans):
    pricing_matrix = {}
    for plan in plans:
        for duree, details in get_subscription_payment_duration_options().items():
            estimate = build_subscription_payment_estimate(entreprise=entreprise, plan=plan, duree=duree)
            pricing_matrix[f"{plan.id}:{duree}"] = {
                "amount_usd": str(estimate["amount_usd"]),
                "currency_code": estimate["currency_code"],
                "estimated_amount": str(estimate["estimated_amount"]),
                "exchange_rate": str(estimate["exchange_rate"]),
                "duration_label": details["label"],
            }
    return pricing_matrix


@transaction.atomic
def create_subscription_payment_request(
    *,
    entreprise,
    plan,
    duree,
    reference_paiement,
    preuve_paiement=None,
    telephone_paiement="",
    utilisateur=None,
):
    if plan is None or not getattr(plan, "actif", False) or normalize_plan_code(plan) not in OFFICIAL_PAID_PLAN_CODES:
        raise ValueError("Plan indisponible.")

    estimate = build_subscription_payment_estimate(entreprise=entreprise, plan=plan, duree=duree)
    montant = estimate["amount_usd"]
    paiement = PaiementAbonnement.objects.create(
        entreprise=entreprise,
        plan=plan,
        duree=duree,
        montant=montant,
        montant_usd=estimate["amount_usd"],
        devise_entreprise=estimate["currency_code"],
        montant_devise_locale_estime=estimate["estimated_amount"],
        taux_change_reference=estimate["exchange_rate"],
        source_taux=estimate["exchange_source"],
        date_taux=estimate.get("exchange_rate_date"),
        telephone_paiement=(telephone_paiement or "").strip(),
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
        metadata={
            "plan_id": plan.id,
            "duree": duree,
            "montant_usd": str(estimate["amount_usd"]),
            "devise_entreprise": estimate["currency_code"],
            "montant_devise_locale_estime": str(estimate["estimated_amount"]),
        },
    )
    return paiement


@transaction.atomic
def create_subscription_plan_request(*, entreprise, plan, utilisateur=None):
    if entreprise is None:
        raise ValueError("Entreprise introuvable.")
    if plan is None or not getattr(plan, "actif", False) or normalize_plan_code(plan) not in OFFICIAL_PAID_PLAN_CODES:
        raise ValueError("Plan indisponible.")

    existing_request = (
        PaiementAbonnement.objects.filter(
            entreprise=entreprise,
            plan=plan,
            statut=PaiementAbonnement.Statut.EN_ATTENTE,
            source_taux="demande_plan",
        )
        .order_by("-date_creation", "-id")
        .first()
    )
    if existing_request is not None:
        return existing_request

    price = get_plan_price_for_company(plan, entreprise)
    currency = price["company_currency"]
    amount = (price["estimated_amount"] or price["official_amount"]).quantize(Decimal("0.01"))
    paiement = PaiementAbonnement.objects.create(
        entreprise=entreprise,
        plan=plan,
        duree=PaiementAbonnement.Duree.MENSUEL,
        montant=amount,
        montant_usd=price["official_amount"],
        devise_entreprise=currency,
        montant_devise_locale_estime=amount,
        taux_change_reference=price["rate"],
        source_taux="demande_plan",
        date_taux=price["rate_date"],
        statut=PaiementAbonnement.Statut.EN_ATTENTE,
        methode_paiement=PaiementAbonnement.Methode.MANUEL,
        reference_paiement=f"Demande plan {plan.nom}"[:120],
        notes_validation="Demande de plan creee depuis l'espace entreprise.",
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="abonnement_plan_demande",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Demande de plan {plan.nom} envoyee.",
        metadata={
            "plan_id": plan.id,
            "plan_nom": plan.nom,
            "montant": str(amount),
            "devise": currency,
        },
    )
    return paiement


def get_pending_subscription_plan_request(entreprise):
    return (
        PaiementAbonnement.objects.filter(
            entreprise=entreprise,
            statut=PaiementAbonnement.Statut.EN_ATTENTE,
            source_taux="demande_plan",
        )
        .select_related("plan", "entreprise")
        .order_by("-date_creation", "-id")
        .first()
    )


@transaction.atomic
def validate_subscription_plan_request(*, entreprise, super_admin=None):
    request = get_pending_subscription_plan_request(entreprise)
    if request is None:
        raise ValueError("Demande de plan introuvable.")

    plan = request.plan
    today = timezone.localdate()
    subscription = get_current_subscription(entreprise)
    previous_plan_id = getattr(subscription, "plan_id", None)
    previous_status = getattr(subscription, "statut", "")

    if subscription is None:
        subscription = AbonnementEntreprise.objects.create(
            entreprise=entreprise,
            plan=plan,
            statut=AbonnementEntreprise.Statut.ACTIF,
            date_debut=today,
            date_fin=today + timedelta(days=plan.duree_jours),
            essai=False,
            actif=True,
        )
    else:
        subscription.plan = plan
        subscription.statut = AbonnementEntreprise.Statut.ACTIF
        subscription.actif = True
        subscription.essai = False
        if not subscription.date_debut or subscription.date_debut > today:
            subscription.date_debut = today
        if not subscription.date_fin or subscription.date_fin < today:
            subscription.date_fin = today + timedelta(days=plan.duree_jours)
        update_fields = ["plan", "statut", "actif", "essai", "date_debut", "date_fin"]
        subscription.save(update_fields=update_fields)

    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)

    request.statut = PaiementAbonnement.Statut.APPROUVEE
    request.date_validation = timezone.now()
    request.valide_par = super_admin
    request.notes_validation = "Demande de plan validee par super admin. Paiement manuel a enregistrer separement si necessaire."
    request.save(update_fields=["statut", "date_validation", "valide_par", "notes_validation"])

    record_audit_event(
        entreprise=entreprise,
        utilisateur=super_admin,
        action="abonnement_plan_demande_validee",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=request.id,
        description=f"Demande de plan {plan.nom} validee.",
        metadata={
            "plan_id": plan.id,
            "plan_nom": plan.nom,
            "previous_plan_id": previous_plan_id,
            "previous_status": previous_status,
            "subscription_id": subscription.id,
            "payment_required": True,
        },
    )
    return subscription, request


@transaction.atomic
def refuse_subscription_plan_request(*, entreprise, super_admin=None, notes_validation=""):
    request = get_pending_subscription_plan_request(entreprise)
    if request is None:
        raise ValueError("Demande de plan introuvable.")

    request.statut = PaiementAbonnement.Statut.REFUSE
    request.date_validation = timezone.now()
    request.valide_par = super_admin
    request.notes_validation = (notes_validation or "Demande de plan refusee par super admin.").strip()
    request.save(update_fields=["statut", "date_validation", "valide_par", "notes_validation"])

    record_audit_event(
        entreprise=entreprise,
        utilisateur=super_admin,
        action="abonnement_plan_demande_refusee",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=request.id,
        description=f"Demande de plan {request.plan.nom} refusee.",
        metadata={"plan_id": request.plan_id, "plan_nom": request.plan.nom},
    )
    return request


@transaction.atomic
def validate_subscription_payment(*, paiement, super_admin, notes_validation=""):
    if paiement.statut != PaiementAbonnement.Statut.EN_ATTENTE:
        raise ValueError("Seuls les paiements en attente peuvent etre valides.")
    duration_days = get_subscription_payment_duration_days(paiement.duree)
    today = timezone.localdate()
    subscription = activate_subscription_for_entreprise(
        entreprise=paiement.entreprise,
        plan=paiement.plan,
        utilisateur=super_admin,
        duration_days=duration_days,
        prolong_existing=True,
    )
    paiement.statut = PaiementAbonnement.Statut.VALIDE
    paiement.date_validation = timezone.now()
    paiement.date_paiement = paiement.date_paiement or paiement.date_validation
    paiement.periode_debut = paiement.periode_debut or today
    paiement.periode_fin = paiement.periode_fin or subscription.date_fin
    paiement.valide_par = super_admin
    paiement.notes_validation = (notes_validation or "").strip()
    paiement.save(
        update_fields=[
            "statut",
            "date_validation",
            "date_paiement",
            "periode_debut",
            "periode_fin",
            "valide_par",
            "notes_validation",
        ]
    )
    record_audit_event(
        entreprise=paiement.entreprise,
        utilisateur=super_admin,
        action="paiement_abonnement_valide",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Paiement abonnement valide pour le plan {paiement.plan.nom}.",
        metadata={
            "plan_id": paiement.plan_id,
            "montant_usd": str(paiement.montant_usd or paiement.montant),
            "subscription_id": subscription.id,
        },
    )
    return subscription


@transaction.atomic
def register_manual_subscription_payment(
    *,
    entreprise,
    plan,
    montant,
    devise,
    methode_paiement,
    reference_paiement="",
    periode_jours=30,
    date_paiement=None,
    montant_usd=None,
    taux_change_reference=None,
    super_admin=None,
):
    if entreprise is None:
        raise ValueError("Entreprise introuvable.")
    if plan is None:
        raise ValueError("Veuillez selectionner un plan.")
    if not getattr(plan, "actif", False) or normalize_plan_code(plan) not in OFFICIAL_PAID_PLAN_CODES:
        raise ValueError("Plan indisponible.")

    amount = Decimal(str(montant or "0")).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Le montant du paiement doit etre positif.")

    days = int(periode_jours or 0)
    if days not in {30, 90, 180, 365}:
        raise ValueError("La periode payee est invalide.")

    payment_date = date_paiement or timezone.localdate()
    paid_at = timezone.make_aware(datetime.combine(payment_date, datetime.min.time()))
    today = timezone.localdate()
    current_subscription = get_current_subscription(entreprise)
    starts_from_existing_end = (
        current_subscription is not None
        and current_subscription.actif
        and current_subscription.statut == AbonnementEntreprise.Statut.ACTIF
        and current_subscription.date_fin
        and current_subscription.date_fin >= today
    )
    period_start = current_subscription.date_fin if starts_from_existing_end else today
    period_end = period_start + timedelta(days=days)

    renewal = AbonnementEntreprise.Renouvellement.MANUEL
    if days == 30:
        renewal = AbonnementEntreprise.Renouvellement.MENSUEL
    elif days == 365:
        renewal = AbonnementEntreprise.Renouvellement.ANNUEL

    subscription, _ = AbonnementEntreprise.objects.update_or_create(
        entreprise=entreprise,
        defaults={
            "plan": plan,
            "statut": AbonnementEntreprise.Statut.ACTIF,
            "date_debut": current_subscription.date_debut if starts_from_existing_end and current_subscription.date_debut else today,
            "date_fin": period_end,
            "renouvellement": renewal,
            "essai": False,
            "actif": True,
        },
    )
    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)

    currency = (devise or get_company_currency(entreprise)).strip().upper()
    platform_currency = get_platform_currency()
    conversion_rate = None
    rate_source = "manuel"
    rate_date = None
    try:
        if currency == platform_currency:
            usd_amount = amount
            conversion_rate = Decimal("1")
            rate_source = "identity"
            rate_date = timezone.now()
        elif taux_change_reference:
            conversion_rate = Decimal(str(taux_change_reference))
            if conversion_rate <= 0:
                raise ValueError("Le taux manuel doit etre positif.")
            usd_amount = (amount / conversion_rate).quantize(Decimal("0.01"))
            rate_source = "manuel"
            rate_date = timezone.now()
        elif montant_usd:
            usd_amount = Decimal(str(montant_usd)).quantize(Decimal("0.01"))
            if usd_amount <= 0:
                raise ValueError("Le montant USD manuel doit etre positif.")
            conversion_rate = (amount / usd_amount).quantize(Decimal("0.0001"))
            rate_source = "manuel"
            rate_date = timezone.now()
        else:
            converted = convert_amount(amount, currency, platform_currency)
            usd_amount = converted.amount
            conversion_rate = converted.rate
            rate_source = converted.provider
            rate_date = converted.rate_date
    except ExchangeRateUnavailable:
        usd_amount = Decimal(str(montant_usd or "0")).quantize(Decimal("0.01"))
        if usd_amount <= 0:
            raise ValueError("Conversion indisponible. Saisissez le montant USD ou un taux manuel.")
        conversion_rate = (amount / usd_amount).quantize(Decimal("0.0001"))
        rate_source = "manuel_super_admin"
        rate_date = timezone.now()
    duration_code = PaiementAbonnement.Duree.MENSUEL
    if days == 90:
        duration_code = PaiementAbonnement.Duree.TRIMESTRIEL
    elif days == 180:
        duration_code = PaiementAbonnement.Duree.SEMESTRIEL
    elif days == 365:
        duration_code = PaiementAbonnement.Duree.ANNUEL

    paiement = PaiementAbonnement.objects.create(
        entreprise=entreprise,
        plan=plan,
        duree=duration_code,
        montant=amount,
        montant_usd=usd_amount,
        devise_entreprise=currency,
        montant_devise_locale_estime=amount,
        taux_change_reference=conversion_rate,
        source_taux=rate_source,
        date_taux=rate_date,
        statut=PaiementAbonnement.Statut.VALIDE,
        methode_paiement=methode_paiement or PaiementAbonnement.Methode.MANUEL,
        provider_reference="",
        periode_debut=period_start,
        periode_fin=period_end,
        date_paiement=paid_at,
        date_validation=timezone.now(),
        valide_par=super_admin,
        reference_paiement=(reference_paiement or "Paiement manuel").strip(),
        notes_validation="Paiement manuel enregistre par super admin.",
    )

    record_audit_event(
        entreprise=entreprise,
        utilisateur=super_admin,
        action="paiement_abonnement_enregistre",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Paiement manuel enregistre pour {entreprise.nom}.",
        metadata={
            "plan_id": plan.id,
            "plan_nom": plan.nom,
            "montant": str(amount),
            "montant_usd": str(usd_amount),
            "devise": currency,
            "taux": str(conversion_rate or ""),
            "source_taux": rate_source,
            "periode_jours": days,
            "reference": paiement.reference_paiement,
            "subscription_id": subscription.id,
            "date_fin": str(subscription.date_fin),
        },
    )
    return paiement, subscription


@transaction.atomic
def refuse_subscription_payment(*, paiement, super_admin, notes_validation=""):
    if paiement.statut != PaiementAbonnement.Statut.EN_ATTENTE:
        raise ValueError("Seuls les paiements en attente peuvent etre refuses.")
    paiement.statut = PaiementAbonnement.Statut.REFUSE
    paiement.date_validation = timezone.now()
    paiement.valide_par = super_admin
    paiement.notes_validation = (notes_validation or "").strip()
    paiement.save(update_fields=["statut", "date_validation", "valide_par", "notes_validation"])
    record_audit_event(
        entreprise=paiement.entreprise,
        utilisateur=super_admin,
        action="paiement_abonnement_refuse",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Paiement abonnement refuse pour le plan {paiement.plan.nom}.",
        metadata={"plan_id": paiement.plan_id, "montant_usd": str(paiement.montant_usd or paiement.montant)},
    )
    return paiement


def start_trial_for_entreprise(*, entreprise, plan, utilisateur=None, date_debut=None, trial_days=None):
    existing_subscription = get_current_subscription(entreprise)
    if (
        existing_subscription is None
        or existing_subscription.statut != AbonnementEntreprise.Statut.ESSAI
        or not existing_subscription.essai
    ):
        raise ValueError("La creation de nouveaux essais est desactivee. Activez le plan Gratuit ou un plan payant.")

    date_debut = date_debut or timezone.localdate()
    duration = trial_days or get_default_trial_days() or plan.duree_jours
    base_date = existing_subscription.date_fin if existing_subscription.date_fin and existing_subscription.date_fin >= date_debut else date_debut
    existing_subscription.plan = plan
    existing_subscription.statut = AbonnementEntreprise.Statut.ESSAI
    existing_subscription.date_debut = existing_subscription.date_debut or date_debut
    existing_subscription.date_fin = base_date + timedelta(days=duration)
    existing_subscription.essai = True
    existing_subscription.actif = True
    existing_subscription.save(update_fields=["plan", "statut", "date_debut", "date_fin", "essai", "actif"])
    subscription = existing_subscription
    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="essai_prolonge",
        module="subscription",
        objet_type="AbonnementEntreprise",
        objet_id=subscription.id,
        description=f"Ancien essai prolonge sur le plan {plan.nom}.",
        metadata={"plan_id": plan.id, "plan_nom": plan.nom, "statut": subscription.statut},
    )
    return subscription


def activate_free_plan_for_entreprise(*, entreprise, plan=None, utilisateur=None, date_debut=None):
    date_debut = date_debut or timezone.localdate()
    plan = plan or get_or_create_free_plan()
    date_fin = date_debut + timedelta(days=plan.duree_jours or FREE_PLAN_DURATION_DAYS)
    subscription, _ = AbonnementEntreprise.objects.update_or_create(
        entreprise=entreprise,
        defaults={
            "plan": plan,
            "statut": AbonnementEntreprise.Statut.ACTIF,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "renouvellement": AbonnementEntreprise.Renouvellement.MANUEL,
            "essai": False,
            "actif": True,
        },
    )
    _sync_legacy_entreprise_subscription_fields(entreprise, subscription)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="plan_gratuit_active",
        module="subscription",
        objet_type="AbonnementEntreprise",
        objet_id=subscription.id,
        description=f"Plan gratuit active sur {plan.nom}.",
        metadata={"plan_id": plan.id, "plan_nom": plan.nom, "statut": subscription.statut},
    )
    return subscription


def start_free_plan_for_entreprise(*, entreprise, plan=None, utilisateur=None, date_debut=None):
    return activate_free_plan_for_entreprise(
        entreprise=entreprise,
        plan=plan,
        utilisateur=utilisateur,
        date_debut=date_debut,
    )


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
