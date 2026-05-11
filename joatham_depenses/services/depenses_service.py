from django.db import transaction
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from core.audit import record_audit_event
from core.services.product_policy import get_module_access_denied_message, get_module_access_state
from core.services.quotas import assert_expense_quota_available
from core.services.tenancy import ensure_same_entreprise
from joatham_caisse.models import MouvementCaisse
from joatham_caisse.selectors.session import get_open_session_for_caisse
from joatham_caisse.services.mouvements import record_cash_expense

from ..selectors.depenses import get_depenses_by_entreprise


def list_depenses_for_entreprise(entreprise, *, date_debut=None, date_fin=None, recherche=None):
    queryset = get_depenses_by_entreprise(entreprise)
    if date_debut and date_fin:
        queryset = queryset.filter(date__date__range=[date_debut, date_fin])
    if recherche:
        queryset = queryset.filter(description__icontains=recherche)
    return queryset


def _resolve_cashbox_context(*, entreprise, caisse):
    if caisse is None:
        return None, None
    state = get_module_access_state(entreprise, "caisse_integrations")
    if not state["allowed"]:
        raise ValueError(get_module_access_denied_message("caisse_integrations", state["reason"]))
    ensure_same_entreprise(caisse, entreprise)
    if not caisse.est_active:
        raise ValueError("La caisse selectionnee est inactive.")
    session = get_open_session_for_caisse(caisse)
    if session is None:
        raise ValueError("Aucune session ouverte n'est disponible pour la caisse selectionnee.")
    ensure_same_entreprise(session, entreprise)
    return caisse, session


def create_cash_movement_for_depense(*, depense, entreprise, utilisateur=None):
    if depense.caisse_id is None or depense.session_caisse_id is None:
        raise ValueError("La depense doit etre rattachee a une caisse et a une session ouverte.")
    ensure_same_entreprise(depense, entreprise)
    ensure_same_entreprise(depense.caisse, entreprise)
    ensure_same_entreprise(depense.session_caisse, entreprise)

    if MouvementCaisse.objects.filter(
        entreprise=entreprise,
        source_app="joatham_depenses",
        source_model="Depense",
        source_id=depense.id,
    ).exists():
        raise ValueError("Un mouvement de caisse existe deja pour cette depense.")

    return record_cash_expense(
        entreprise=entreprise,
        caisse=depense.caisse,
        session=depense.session_caisse,
        montant=depense.montant,
        libelle=depense.description,
        reference=f"DEP-{depense.id}",
        commentaire="Depense payee depuis une caisse.",
        source_id=depense.id,
        utilisateur=utilisateur,
    )


@transaction.atomic
def create_depense_for_entreprise(form, entreprise, utilisateur=None):
    assert_expense_quota_available(entreprise)
    caisse, session_caisse = _resolve_cashbox_context(
        entreprise=entreprise,
        caisse=form.cleaned_data.get("caisse"),
    )
    depense = form.save(commit=False)
    depense.entreprise = entreprise
    depense.caisse = caisse
    depense.session_caisse = session_caisse
    depense.save()
    if caisse is not None:
        create_cash_movement_for_depense(depense=depense, entreprise=entreprise, utilisateur=utilisateur)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="depense_creee",
        module="depenses",
        objet_type="Depense",
        objet_id=depense.id,
        description=f"Depense creee: {depense.description}.",
        metadata={
            "montant": str(depense.montant),
            "caisse_id": depense.caisse_id,
            "session_caisse_id": depense.session_caisse_id,
        },
    )
    return depense


def get_depenses_total(queryset):
    return queryset.aggregate(Sum("montant"))["montant__sum"] or 0


def get_depenses_kpis(entreprise):
    queryset = get_depenses_by_entreprise(entreprise)
    today = timezone.localdate()
    month_start = today.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    total = get_depenses_total(queryset)
    today_total = get_depenses_total(queryset.filter(date__date=today))
    month_total = get_depenses_total(queryset.filter(date__date__gte=month_start, date__date__lte=today))
    previous_month_total = get_depenses_total(
        queryset.filter(date__date__gte=previous_month_start, date__date__lte=previous_month_end)
    )
    count = queryset.count()
    average = (total / count) if count else 0

    if previous_month_total:
        evolution_percent = ((month_total - previous_month_total) / previous_month_total) * 100
        evolution_direction = "up" if evolution_percent >= 0 else "down"
        evolution_display = f"{evolution_percent:+.1f}%".replace(".", ",")
    elif month_total:
        evolution_percent = None
        evolution_direction = "up"
        evolution_display = "Nouveau"
    else:
        evolution_percent = 0
        evolution_direction = "flat"
        evolution_display = "0,0%"

    return {
        "count": count,
        "total": total,
        "today_total": today_total,
        "month_total": month_total,
        "average": average,
        "evolution_percent": evolution_percent,
        "evolution_direction": evolution_direction,
        "evolution_display": evolution_display,
    }
