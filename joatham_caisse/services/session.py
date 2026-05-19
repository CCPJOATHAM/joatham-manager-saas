from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.audit import record_audit_event
from core.services.tenancy import ensure_same_entreprise

from ..models import SessionCaisse
from ..selectors.mouvements import get_cash_flow_totals_for_session
from ..selectors.session import get_open_session_for_caisse


def _normalize_non_negative_amount(value, field_label):
    try:
        normalized = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_label} est invalide.") from exc
    if normalized < Decimal("0.00"):
        raise ValueError(f"{field_label} ne peut pas etre negatif.")
    return normalized


def compute_theoretical_balance(session):
    totals = get_cash_flow_totals_for_session(session)
    total_entrees = Decimal(str(totals["total_entrees"]))
    total_sorties = Decimal(str(totals["total_sorties"]))
    return Decimal(str(session.solde_initial)) + total_entrees - total_sorties


@transaction.atomic
def open_session(*, entreprise, caisse, utilisateur, solde_initial=Decimal("0.00"), commentaire=""):
    ensure_same_entreprise(caisse, entreprise)
    solde_initial = _normalize_non_negative_amount(solde_initial, "Le solde initial")
    if not caisse.est_active:
        raise ValueError("Cette caisse est inactive.")
    if get_open_session_for_caisse(caisse) is not None:
        raise ValueError("Une session est deja ouverte pour cette caisse.")

    session = SessionCaisse.objects.create(
        entreprise=entreprise,
        caisse=caisse,
        utilisateur_ouverture=utilisateur,
        solde_initial=solde_initial,
        commentaire_ouverture=(commentaire or "").strip(),
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_session_opened",
        module="caisse",
        objet_type="SessionCaisse",
        objet_id=session.id,
        description=f"Session ouverte pour la caisse {caisse.nom}.",
        metadata={"caisse_id": caisse.id, "solde_initial": str(session.solde_initial)},
    )
    return session


open_session_for_caisse = open_session


@transaction.atomic
def close_session(*, entreprise, session, utilisateur, solde_reel, commentaire=""):
    ensure_same_entreprise(session, entreprise)
    if session.statut != SessionCaisse.Statut.OUVERTE:
        raise ValueError("Seule une session ouverte peut etre fermee.")

    solde_theorique = compute_theoretical_balance(session)
    solde_reel = _normalize_non_negative_amount(solde_reel, "Le solde reel")
    ecart = solde_reel - solde_theorique
    session.solde_theorique = solde_theorique
    session.solde_reel = solde_reel
    session.ecart = ecart
    session.statut = SessionCaisse.Statut.FERMEE
    session.utilisateur_fermeture = utilisateur
    session.date_fermeture = timezone.now()
    session.commentaire_fermeture = (commentaire or "").strip()
    session.save(
        update_fields=[
            "solde_theorique",
            "solde_reel",
            "ecart",
            "statut",
            "utilisateur_fermeture",
            "date_fermeture",
            "commentaire_fermeture",
            "date_modification",
        ]
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_session_closed",
        module="caisse",
        objet_type="SessionCaisse",
        objet_id=session.id,
        description=f"Session fermee pour la caisse {session.caisse.nom}.",
        metadata={
            "caisse_id": session.caisse_id,
            "solde_theorique": str(solde_theorique),
            "solde_reel": str(solde_reel),
            "ecart": str(ecart),
        },
    )
    return session


@transaction.atomic
def cancel_session(*, entreprise, session, utilisateur, commentaire=""):
    ensure_same_entreprise(session, entreprise)
    if session.statut == SessionCaisse.Statut.VALIDEE:
        raise ValueError("Une session validee ne peut plus etre annulee.")
    if session.validations.exists():
        raise ValueError("Une session deja traitee ne peut plus etre annulee.")

    session.statut = SessionCaisse.Statut.ANNULEE
    if not session.date_fermeture:
        session.date_fermeture = timezone.now()
    session.utilisateur_fermeture = utilisateur
    session.commentaire_fermeture = (commentaire or "").strip()
    session.save(
        update_fields=[
            "statut",
            "date_fermeture",
            "utilisateur_fermeture",
            "commentaire_fermeture",
            "date_modification",
        ]
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_session_cancelled",
        module="caisse",
        objet_type="SessionCaisse",
        objet_id=session.id,
        description=f"Session annulee pour la caisse {session.caisse.nom}.",
        metadata={"caisse_id": session.caisse_id},
    )
    return session
