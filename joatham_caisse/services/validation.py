from django.db import transaction

from core.audit import record_audit_event
from core.services.tenancy import ensure_same_entreprise

from ..models import SessionCaisse, ValidationCaisse

@transaction.atomic
def validate_session(*, entreprise, session, utilisateur, commentaire=""):
    ensure_same_entreprise(session, entreprise)
    if session.statut != SessionCaisse.Statut.FERMEE:
        raise ValueError("Seule une session fermee peut etre validee.")
    if session.validations.exists():
        raise ValueError("Cette session a deja fait l'objet d'une validation.")

    validation = ValidationCaisse.objects.create(
        entreprise=entreprise,
        session=session,
        validee_par=utilisateur,
        decision=ValidationCaisse.Decision.VALIDEE,
        commentaire=(commentaire or "").strip(),
    )
    session.statut = SessionCaisse.Statut.VALIDEE
    session.save(update_fields=["statut", "date_modification"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_session_validated",
        module="caisse",
        objet_type="ValidationCaisse",
        objet_id=validation.id,
        description=f"Session validee pour la caisse {session.caisse.nom}.",
        metadata={"session_id": session.id, "decision": validation.decision},
    )
    return validation


@transaction.atomic
def reject_session(*, entreprise, session, utilisateur, commentaire=""):
    ensure_same_entreprise(session, entreprise)
    if session.statut != SessionCaisse.Statut.FERMEE:
        raise ValueError("Seule une session fermee peut etre rejetee.")
    if session.validations.exists():
        raise ValueError("Cette session a deja fait l'objet d'une validation.")

    validation = ValidationCaisse.objects.create(
        entreprise=entreprise,
        session=session,
        validee_par=utilisateur,
        decision=ValidationCaisse.Decision.REJETEE,
        commentaire=(commentaire or "").strip(),
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_session_rejected",
        module="caisse",
        objet_type="ValidationCaisse",
        objet_id=validation.id,
        description=f"Session rejetee pour la caisse {session.caisse.nom}.",
        metadata={"session_id": session.id, "decision": validation.decision},
    )
    return validation
