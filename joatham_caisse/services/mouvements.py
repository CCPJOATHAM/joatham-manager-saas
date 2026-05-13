from django.db import transaction

from core.audit import record_audit_event
from core.services.tenancy import ensure_same_entreprise

from ..models import MouvementCaisse, SessionCaisse


def _validate_open_session(entreprise, session, caisse):
    ensure_same_entreprise(session, entreprise)
    ensure_same_entreprise(caisse, entreprise)
    if session.caisse_id != caisse.id:
        raise ValueError("Cette session n'appartient pas a la caisse selectionnee.")
    if session.statut != SessionCaisse.Statut.OUVERTE:
        raise ValueError("Les mouvements ne peuvent etre ajoutes que sur une session ouverte.")
    if not caisse.est_active:
        raise ValueError("Cette caisse est inactive.")


@transaction.atomic
def record_mouvement(
    *,
    entreprise,
    caisse,
    session,
    type_mouvement,
    montant,
    libelle,
    reference="",
    commentaire="",
    source_app="",
    source_model="",
    source_id=None,
    utilisateur=None,
    statut=MouvementCaisse.Statut.CONFIRME,
    moyen_paiement="cash",
):
    _validate_open_session(entreprise, session, caisse)
    mouvement = MouvementCaisse.objects.create(
        entreprise=entreprise,
        caisse=caisse,
        session=session,
        type_mouvement=type_mouvement,
        montant=montant,
        devise=caisse.devise,
        libelle=(libelle or "").strip(),
        reference=(reference or "").strip(),
        moyen_paiement=(moyen_paiement or "cash").strip(),
        source_app=(source_app or "").strip(),
        source_model=(source_model or "").strip(),
        source_id=source_id,
        cree_par=utilisateur,
        commentaire=(commentaire or "").strip(),
        statut=statut,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_movement_created",
        module="caisse",
        objet_type="MouvementCaisse",
        objet_id=mouvement.id,
        description=f"Mouvement {mouvement.type_mouvement} enregistre pour la caisse {caisse.nom}.",
        metadata={
            "caisse_id": caisse.id,
            "session_id": session.id,
            "type_mouvement": mouvement.type_mouvement,
            "montant": str(mouvement.montant),
            "reference": mouvement.reference,
            "moyen_paiement": mouvement.moyen_paiement,
            "source_app": mouvement.source_app,
            "source_model": mouvement.source_model,
            "source_id": mouvement.source_id,
        },
    )
    return mouvement


def record_cash_entry(*, entreprise, caisse, session, montant, libelle, reference="", commentaire="", utilisateur=None):
    return record_mouvement(
        entreprise=entreprise,
        caisse=caisse,
        session=session,
        type_mouvement=MouvementCaisse.TypeMouvement.ENTREE,
        montant=montant,
        libelle=libelle,
        reference=reference,
        commentaire=commentaire,
        utilisateur=utilisateur,
        moyen_paiement="cash",
    )


def record_cash_exit(*, entreprise, caisse, session, montant, libelle, reference="", commentaire="", utilisateur=None):
    return record_mouvement(
        entreprise=entreprise,
        caisse=caisse,
        session=session,
        type_mouvement=MouvementCaisse.TypeMouvement.SORTIE,
        montant=montant,
        libelle=libelle,
        reference=reference,
        commentaire=commentaire,
        utilisateur=utilisateur,
        moyen_paiement="cash",
    )


def record_cash_expense(
    *,
    entreprise,
    caisse,
    session,
    montant,
    libelle,
    reference="",
    commentaire="",
    source_id=None,
    utilisateur=None,
):
    return record_mouvement(
        entreprise=entreprise,
        caisse=caisse,
        session=session,
        type_mouvement=MouvementCaisse.TypeMouvement.DEPENSE,
        montant=montant,
        libelle=libelle,
        reference=reference,
        commentaire=commentaire,
        source_app="joatham_depenses",
        source_model="Depense" if source_id else "",
        source_id=source_id,
        utilisateur=utilisateur,
        moyen_paiement="cash",
    )


def record_invoice_cash_payment(
    *,
    entreprise,
    caisse,
    session,
    montant,
    libelle,
    reference="",
    commentaire="",
    facture=None,
    paiement=None,
    source_app="",
    source_model="",
    source_id=None,
    utilisateur=None,
    moyen_paiement="cash",
):
    resolved_source_app = (source_app or "").strip()
    resolved_source_model = (source_model or "").strip()
    resolved_source_id = source_id

    if paiement is not None and not resolved_source_model:
        resolved_source_app = resolved_source_app or "joatham_billing"
        resolved_source_model = "PaiementFacture"
        resolved_source_id = getattr(paiement, "id", None)
    elif facture is not None and not resolved_source_model:
        resolved_source_app = resolved_source_app or "joatham_billing"
        resolved_source_model = "Facture"
        resolved_source_id = getattr(facture, "id", None)

    return record_mouvement(
        entreprise=entreprise,
        caisse=caisse,
        session=session,
        type_mouvement=MouvementCaisse.TypeMouvement.PAIEMENT_FACTURE,
        montant=montant,
        libelle=libelle,
        reference=reference,
        commentaire=commentaire,
        source_app=resolved_source_app,
        source_model=resolved_source_model,
        source_id=resolved_source_id,
        utilisateur=utilisateur,
        moyen_paiement=moyen_paiement,
    )


def record_adjustment(*, entreprise, caisse, session, montant, libelle, reference="", commentaire="", utilisateur=None):
    return record_mouvement(
        entreprise=entreprise,
        caisse=caisse,
        session=session,
        type_mouvement=MouvementCaisse.TypeMouvement.AJUSTEMENT,
        montant=montant,
        libelle=libelle,
        reference=reference,
        commentaire=commentaire,
        utilisateur=utilisateur,
        moyen_paiement="cash",
    )
