from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.audit import record_audit_event
from core.services.product_policy import get_module_access_denied_message, get_module_access_state
from joatham_caisse.models import Caisse, MouvementCaisse
from joatham_caisse.selectors.session import get_open_session_for_caisse
from joatham_caisse.services.mouvements import record_mouvement
from joatham_users.permissions import user_has_permission

from ..models import AvanceSalaire, DemandeConge, DocumentRH, Employe, PaiementSalaire, Poste, Presence


User = get_user_model()
USER_LINK_UNCHANGED = object()


class RhOperationError(ValueError):
    pass


def _clean_required(value, message):
    cleaned = (value or "").strip()
    if not cleaned:
        raise RhOperationError(message)
    return cleaned


def _normalize_date(value, message):
    if value in {None, ""}:
        raise RhOperationError(message)
    if isinstance(value, str):
        parsed = parse_date(value)
        if parsed is None:
            raise RhOperationError(message)
        return parsed
    return value


def _normalize_optional_date(value):
    if value in {None, ""}:
        return None
    return _normalize_date(value, "La date du document est invalide.")


def _normalize_salary(value):
    if value in {None, ""}:
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RhOperationError("Le salaire de base est invalide.") from exc
    if amount < 0:
        raise RhOperationError("Le salaire de base ne peut pas etre negatif.")
    return amount




def _normalize_non_negative_amount(value, message):
    if value in {None, ""}:
        return Decimal("0.00")
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RhOperationError(message) from exc
    if amount < 0:
        raise RhOperationError(message)
    return amount


def _normalize_positive_amount(value, message):
    amount = _normalize_non_negative_amount(value, message)
    if amount <= 0:
        raise RhOperationError(message)
    return amount


def _normalize_period_month(value):
    try:
        month = int(value)
    except (TypeError, ValueError) as exc:
        raise RhOperationError("Le mois de paie est invalide.") from exc
    if month < 1 or month > 12:
        raise RhOperationError("Le mois de paie est invalide.")
    return month


def _normalize_period_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise RhOperationError("L'annee de paie est invalide.") from exc
    if year < 2000:
        raise RhOperationError("L'annee de paie est invalide.")
    return year


def _validate_choice(value, choices, message):
    accepted = {choice[0] for choice in choices}
    if value not in accepted:
        raise RhOperationError(message)
    return value


def _ensure_same_entreprise(instance, entreprise, message):
    if instance is not None and getattr(instance, "entreprise_id", None) != getattr(entreprise, "id", None):
        raise RhOperationError(message)
    return instance


def _record_blocked_user_link(*, entreprise, employe, user, utilisateur, action, description, reason):
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action=action,
        module="rh",
        objet_type="Employe",
        objet_id=getattr(employe, "id", None),
        description=description,
        metadata={
            "employe_id": getattr(employe, "id", None),
            "user_id": getattr(user, "id", None),
            "user_email": getattr(user, "email", "") or getattr(user, "username", ""),
            "reason": reason,
        },
    )


def _ensure_user_link_can_be_managed(*, entreprise, employe, user, utilisateur):
    if user_has_permission(utilisateur, "rh.link_user"):
        return

    message = "Seul le proprietaire peut modifier la liaison avec un compte utilisateur."
    _record_blocked_user_link(
        entreprise=entreprise,
        employe=employe,
        user=user,
        utilisateur=utilisateur,
        action="tentative_liaison_non_autorisee_bloquee",
        description=message,
        reason="unauthorized_actor",
    )
    raise RhOperationError(message)


def _record_user_link_change(*, entreprise, employe, previous_user_id, current_user, utilisateur):
    current_user_id = getattr(current_user, "id", None)
    if previous_user_id == current_user_id:
        return

    if previous_user_id and current_user_id:
        action = "employe_user_liaison_modifiee"
        description = f"Liaison compte utilisateur modifiee pour l'employe {employe.matricule}."
    elif current_user_id:
        action = "employe_user_lie"
        description = f"Compte utilisateur lie a l'employe {employe.matricule}."
    else:
        action = "employe_user_delie"
        description = f"Compte utilisateur delie de l'employe {employe.matricule}."

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action=action,
        module="rh",
        objet_type="Employe",
        objet_id=employe.id,
        description=description,
        metadata={
            "employe_id": employe.id,
            "previous_user_id": previous_user_id,
            "current_user_id": current_user_id,
        },
    )


def validate_employe_user_link(employe, user, entreprise, *, utilisateur=None):
    if user is None:
        return None

    if getattr(user, "normalized_role", None) == User.Role.SUPER_ADMIN:
        message = "Un super admin ne peut pas etre lie a un employe d'entreprise."
        _record_blocked_user_link(
            entreprise=entreprise,
            employe=employe,
            user=user,
            utilisateur=utilisateur,
            action="tentative_liaison_super_admin_bloquee",
            description=message,
            reason="super_admin",
        )
        raise RhOperationError(message)

    if getattr(user, "entreprise_id", None) != getattr(entreprise, "id", None):
        message = "Le compte utilisateur selectionne appartient a une autre entreprise."
        _record_blocked_user_link(
            entreprise=entreprise,
            employe=employe,
            user=user,
            utilisateur=utilisateur,
            action="tentative_liaison_cross_tenant_bloquee",
            description=message,
            reason="cross_tenant",
        )
        raise RhOperationError(message)

    linked_employes = Employe.objects.filter(user=user)
    if employe.pk:
        linked_employes = linked_employes.exclude(pk=employe.pk)
    if linked_employes.exists():
        raise RhOperationError("Ce compte utilisateur est deja lie a un autre employe RH.")

    return user


@transaction.atomic
def create_poste(*, entreprise, nom, description="", actif=True, utilisateur=None):
    poste = Poste(
        entreprise=entreprise,
        nom=_clean_required(nom, "Le nom du poste est obligatoire."),
        description=(description or "").strip(),
        actif=bool(actif),
    )
    try:
        poste.save()
    except IntegrityError as exc:
        raise RhOperationError("Un poste avec ce nom existe deja pour cette entreprise.") from exc

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="rh_poste_created",
        module="rh",
        objet_type="Poste",
        objet_id=poste.id,
        description=f"Poste RH cree : {poste.nom}.",
        metadata={"poste_id": poste.id},
    )
    return poste


def create_employe(
    *,
    entreprise,
    matricule,
    nom,
    prenom,
    date_embauche,
    poste=None,
    sexe="",
    telephone="",
    email="",
    adresse="",
    type_contrat=Employe.TypeContrat.CDI,
    salaire_base=None,
    statut=Employe.Statut.ACTIF,
    actif=True,
    user=None,
    utilisateur=None,
):
    _ensure_same_entreprise(poste, entreprise, "Le poste selectionne appartient a une autre entreprise.")
    employe = Employe(
        entreprise=entreprise,
        user=user,
        matricule=_clean_required(matricule, "Le matricule est obligatoire."),
        nom=_clean_required(nom, "Le nom est obligatoire."),
        prenom=_clean_required(prenom, "Le prenom est obligatoire."),
        sexe=sexe or "",
        telephone=(telephone or "").strip(),
        email=(email or "").strip(),
        adresse=(adresse or "").strip(),
        poste=poste,
        type_contrat=_validate_choice(type_contrat, Employe.TypeContrat.choices, "Le type de contrat est invalide."),
        date_embauche=_normalize_date(date_embauche, "La date d'embauche est obligatoire."),
        salaire_base=_normalize_salary(salaire_base),
        statut=_validate_choice(statut, Employe.Statut.choices, "Le statut employe est invalide."),
        actif=bool(actif),
    )
    if employe.sexe:
        _validate_choice(employe.sexe, Employe.Sexe.choices, "Le sexe selectionne est invalide.")
    if user is not None:
        _ensure_user_link_can_be_managed(
            entreprise=entreprise,
            employe=employe,
            user=user,
            utilisateur=utilisateur,
        )
        validate_employe_user_link(employe, user, entreprise, utilisateur=utilisateur)

    try:
        with transaction.atomic():
            employe.save()
            record_audit_event(
                entreprise=entreprise,
                utilisateur=utilisateur,
                action="rh_employe_created",
                module="rh",
                objet_type="Employe",
                objet_id=employe.id,
                description=f"Employe RH cree : {employe.matricule}.",
                metadata={"employe_id": employe.id, "matricule": employe.matricule},
            )
            if user:
                _record_user_link_change(
                    entreprise=entreprise,
                    employe=employe,
                    previous_user_id=None,
                    current_user=user,
                    utilisateur=utilisateur,
                )
    except IntegrityError as exc:
        raise RhOperationError("Un employe avec ce matricule existe deja pour cette entreprise.") from exc
    return employe


def update_employe(
    *,
    entreprise,
    employe,
    matricule,
    nom,
    prenom,
    date_embauche,
    poste=None,
    sexe="",
    telephone="",
    email="",
    adresse="",
    type_contrat=Employe.TypeContrat.CDI,
    salaire_base=None,
    statut=Employe.Statut.ACTIF,
    actif=True,
    user=USER_LINK_UNCHANGED,
    utilisateur=None,
):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    _ensure_same_entreprise(poste, entreprise, "Le poste selectionne appartient a une autre entreprise.")
    previous_user_id = employe.user_id
    user_link_changed = user is not USER_LINK_UNCHANGED
    if user_link_changed:
        _ensure_user_link_can_be_managed(
            entreprise=entreprise,
            employe=employe,
            user=user,
            utilisateur=utilisateur,
        )
        validate_employe_user_link(employe, user, entreprise, utilisateur=utilisateur)
        employe.user = user
    employe.matricule = _clean_required(matricule, "Le matricule est obligatoire.")
    employe.nom = _clean_required(nom, "Le nom est obligatoire.")
    employe.prenom = _clean_required(prenom, "Le prenom est obligatoire.")
    employe.sexe = sexe or ""
    if employe.sexe:
        _validate_choice(employe.sexe, Employe.Sexe.choices, "Le sexe selectionne est invalide.")
    employe.telephone = (telephone or "").strip()
    employe.email = (email or "").strip()
    employe.adresse = (adresse or "").strip()
    employe.poste = poste
    employe.type_contrat = _validate_choice(type_contrat, Employe.TypeContrat.choices, "Le type de contrat est invalide.")
    employe.date_embauche = _normalize_date(date_embauche, "La date d'embauche est obligatoire.")
    employe.salaire_base = _normalize_salary(salaire_base)
    employe.statut = _validate_choice(statut, Employe.Statut.choices, "Le statut employe est invalide.")
    employe.actif = bool(actif)

    try:
        with transaction.atomic():
            employe.save()
            if user_link_changed:
                _record_user_link_change(
                    entreprise=entreprise,
                    employe=employe,
                    previous_user_id=previous_user_id,
                    current_user=employe.user,
                    utilisateur=utilisateur,
                )
            record_audit_event(
                entreprise=entreprise,
                utilisateur=utilisateur,
                action="rh_employe_updated",
                module="rh",
                objet_type="Employe",
                objet_id=employe.id,
                description=f"Employe RH modifie : {employe.matricule}.",
                metadata={"employe_id": employe.id, "matricule": employe.matricule},
            )
    except IntegrityError as exc:
        raise RhOperationError("Un employe avec ce matricule existe deja pour cette entreprise.") from exc
    return employe


@transaction.atomic
def record_presence(*, entreprise, employe, date, statut, heure_arrivee=None, heure_depart=None, note="", utilisateur=None):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    normalized_date = _normalize_date(date, "La date de presence est obligatoire.")
    normalized_status = _validate_choice(statut, Presence.Statut.choices, "Le statut de presence est invalide.")
    if Presence.objects.filter(entreprise=entreprise, employe=employe, date=normalized_date).exists():
        raise RhOperationError("Une presence existe deja pour cet employe a cette date.")

    presence = Presence.objects.create(
        entreprise=entreprise,
        employe=employe,
        date=normalized_date,
        statut=normalized_status,
        heure_arrivee=heure_arrivee,
        heure_depart=heure_depart,
        note=(note or "").strip(),
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="rh_presence_recorded",
        module="rh",
        objet_type="Presence",
        objet_id=presence.id,
        description=f"Presence RH enregistree pour {employe.matricule}.",
        metadata={"presence_id": presence.id, "employe_id": employe.id, "date": normalized_date},
    )
    return presence


def _ensure_valid_date_range(date_debut, date_fin):
    normalized_start = _normalize_date(date_debut, "La date de debut est obligatoire.")
    normalized_end = _normalize_date(date_fin, "La date de fin est obligatoire.")
    if normalized_end < normalized_start:
        raise RhOperationError("La date de fin doit etre superieure ou egale a la date de debut.")
    return normalized_start, normalized_end


@transaction.atomic
def create_conge(
    *,
    entreprise,
    employe,
    type_conge,
    date_debut,
    date_fin,
    motif="",
    statut=DemandeConge.Statut.EN_ATTENTE,
    utilisateur=None,
):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    normalized_start, normalized_end = _ensure_valid_date_range(date_debut, date_fin)
    conge = DemandeConge.objects.create(
        entreprise=entreprise,
        employe=employe,
        type_conge=_validate_choice(type_conge, DemandeConge.TypeConge.choices, "Le type de conge est invalide."),
        date_debut=normalized_start,
        date_fin=normalized_end,
        motif=(motif or "").strip(),
        statut=_validate_choice(statut, DemandeConge.Statut.choices, "Le statut de conge est invalide."),
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="rh_conge_created",
        module="rh",
        objet_type="DemandeConge",
        objet_id=conge.id,
        description=f"Demande de conge creee pour {employe.matricule}.",
        metadata={"conge_id": conge.id, "employe_id": employe.id, "statut": conge.statut},
    )
    return conge


def _ensure_conge_can_be_decided(conge):
    if conge.statut == DemandeConge.Statut.ANNULE:
        raise RhOperationError("Une demande annulee ne peut pas etre approuvee ou refusee.")
    if conge.statut == DemandeConge.Statut.APPROUVE:
        raise RhOperationError("Une demande approuvee ne peut plus etre modifiee.")
    if conge.statut == DemandeConge.Statut.REFUSE:
        raise RhOperationError("Une demande deja refusee ne peut plus etre modifiee.")
    return conge


@transaction.atomic
def decide_conge(*, entreprise, conge, statut, decide_par=None, commentaire_decision=""):
    _ensure_same_entreprise(conge, entreprise, "La demande de conge appartient a une autre entreprise.")
    _ensure_conge_can_be_decided(conge)
    if statut not in {DemandeConge.Statut.APPROUVE, DemandeConge.Statut.REFUSE}:
        raise RhOperationError("La decision de conge est invalide.")
    conge.statut = statut
    conge.approuve_par = decide_par
    conge.date_decision = timezone.now()
    conge.commentaire_decision = (commentaire_decision or "").strip()
    conge.save(update_fields=["statut", "approuve_par", "date_decision", "commentaire_decision", "updated_at"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=decide_par,
        action="rh_conge_decided",
        module="rh",
        objet_type="DemandeConge",
        objet_id=conge.id,
        description=f"Demande de conge {conge.statut} pour {conge.employe.matricule}.",
        metadata={"conge_id": conge.id, "statut": conge.statut},
    )
    return conge


def approve_conge(*, entreprise, conge, decide_par=None, commentaire_decision=""):
    return decide_conge(
        entreprise=entreprise,
        conge=conge,
        statut=DemandeConge.Statut.APPROUVE,
        decide_par=decide_par,
        commentaire_decision=commentaire_decision,
    )


def refuse_conge(*, entreprise, conge, decide_par=None, commentaire_decision=""):
    return decide_conge(
        entreprise=entreprise,
        conge=conge,
        statut=DemandeConge.Statut.REFUSE,
        decide_par=decide_par,
        commentaire_decision=commentaire_decision,
    )


@transaction.atomic
def create_document_rh(
    *,
    entreprise,
    employe,
    type_document,
    titre,
    description="",
    date_document=None,
    utilisateur=None,
):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    document = DocumentRH.objects.create(
        entreprise=entreprise,
        employe=employe,
        type_document=_validate_choice(type_document, DocumentRH.TypeDocument.choices, "Le type de document RH est invalide."),
        titre=_clean_required(titre, "Le titre du document est obligatoire."),
        description=(description or "").strip(),
        date_document=_normalize_optional_date(date_document),
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="rh_document_created",
        module="rh",
        objet_type="DocumentRH",
        objet_id=document.id,
        description=f"Document RH cree : {document.titre}.",
        metadata={"document_id": document.id, "employe_id": employe.id, "type_document": document.type_document},
    )
    return document

@transaction.atomic
def create_avance_salaire(
    *,
    entreprise,
    employe,
    date_avance,
    montant,
    motif="",
    statut=AvanceSalaire.Statut.VALIDEE,
    mode_paiement=AvanceSalaire.ModePaiement.ESPECES,
    reference="",
    utilisateur=None,
):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    avance = AvanceSalaire.objects.create(
        entreprise=entreprise,
        employe=employe,
        date_avance=_normalize_date(date_avance, "La date de l'avance est obligatoire."),
        montant=_normalize_positive_amount(montant, "Le montant de l'avance doit etre strictement positif."),
        motif=(motif or "").strip(),
        statut=_validate_choice(statut, AvanceSalaire.Statut.choices, "Le statut de l'avance est invalide."),
        mode_paiement=_validate_choice(mode_paiement, AvanceSalaire.ModePaiement.choices, "Le mode de paiement est invalide."),
        reference=(reference or "").strip(),
        cree_par=utilisateur,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="rh_avance_salaire_created",
        module="rh",
        objet_type="AvanceSalaire",
        objet_id=avance.id,
        description=f"Avance sur salaire creee pour {employe.matricule}.",
        metadata={"avance_id": avance.id, "employe_id": employe.id, "montant": str(avance.montant)},
    )
    return avance


@transaction.atomic
def cancel_avance_salaire(*, entreprise, avance, utilisateur=None):
    _ensure_same_entreprise(avance, entreprise, "L'avance selectionnee appartient a une autre entreprise.")
    if avance.statut == AvanceSalaire.Statut.ANNULEE:
        return avance
    avance.statut = AvanceSalaire.Statut.ANNULEE
    avance.save(update_fields=["statut", "updated_at"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="rh_avance_salaire_cancelled",
        module="rh",
        objet_type="AvanceSalaire",
        objet_id=avance.id,
        description=f"Avance sur salaire annulee pour {avance.employe.matricule}.",
        metadata={"avance_id": avance.id, "employe_id": avance.employe_id},
    )
    return avance


def get_total_avances_salaire_valides_du_mois(*, entreprise, employe, periode_mois, periode_annee):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    month = _normalize_period_month(periode_mois)
    year = _normalize_period_year(periode_annee)
    total = Decimal("0.00")
    for avance in AvanceSalaire.objects.filter(
        entreprise=entreprise,
        employe=employe,
        statut=AvanceSalaire.Statut.VALIDEE,
        date_avance__month=month,
        date_avance__year=year,
    ):
        total += avance.montant or Decimal("0.00")
    return total.quantize(Decimal("0.01"))


def calculer_net_salaire(*, salaire_base, primes=0, retenues=0, total_avances_deduites=0):
    salaire_base = _normalize_non_negative_amount(salaire_base, "Le salaire de base est invalide.")
    primes = _normalize_non_negative_amount(primes, "Le montant des primes est invalide.")
    retenues = _normalize_non_negative_amount(retenues, "Le montant des retenues est invalide.")
    total_avances_deduites = _normalize_non_negative_amount(total_avances_deduites, "Le total des avances est invalide.")
    return max(salaire_base + primes - retenues - total_avances_deduites, Decimal("0.00")).quantize(Decimal("0.01"))


def _resolve_paiement_salaire_cashbox_context(*, entreprise, caisse, utilisateur=None):
    if caisse in {None, ""}:
        return None, None
    state = get_module_access_state(entreprise, "caisse_integrations")
    if not state["allowed"]:
        raise RhOperationError(get_module_access_denied_message("caisse_integrations", state["reason"]))
    if utilisateur is not None and not user_has_permission(utilisateur, "caisse.add_movement"):
        raise RhOperationError("Vous n'avez pas les droits pour créer un mouvement de caisse.")
    if not isinstance(caisse, Caisse):
        try:
            caisse = Caisse.objects.get(id=caisse)
        except (Caisse.DoesNotExist, TypeError, ValueError) as exc:
            raise RhOperationError("La caisse sélectionnée est introuvable.") from exc
    _ensure_same_entreprise(caisse, entreprise, "La caisse sélectionnée appartient à une autre entreprise.")
    if not caisse.est_active:
        raise RhOperationError("La caisse sélectionnée est inactive.")
    session = get_open_session_for_caisse(caisse)
    if session is None:
        raise RhOperationError("Aucune session de caisse ouverte pour cette caisse.")
    _ensure_same_entreprise(session, entreprise, "La session de caisse appartient à une autre entreprise.")
    return caisse, session


def _map_salary_payment_method_to_cash_method(mode_paiement):
    return {
        PaiementSalaire.ModePaiement.ESPECES: "cash",
        PaiementSalaire.ModePaiement.MOBILE_MONEY: "mobile_money",
        PaiementSalaire.ModePaiement.VIREMENT: "bank_transfer",
        PaiementSalaire.ModePaiement.AUTRE: "other",
    }.get(mode_paiement or "", "other")


def _build_paiement_salaire_cash_reference(paiement):
    return paiement.reference or f"RH-SAL-{paiement.id}"


def _build_paiement_salaire_cash_label(paiement):
    employee_name = f"{paiement.employe.nom} {paiement.employe.prenom}".strip()
    return f"Paiement salaire - {employee_name} - {paiement.periode_mois:02d}/{paiement.periode_annee}"


def create_cash_movement_for_paiement_salaire(*, paiement, entreprise, utilisateur=None):
    _ensure_same_entreprise(paiement, entreprise, "Le paiement de salaire appartient à une autre entreprise.")
    if paiement.mouvement_caisse_id:
        return paiement.mouvement_caisse
    if paiement.caisse_id is None or paiement.session_caisse_id is None:
        raise RhOperationError("Le paiement de salaire doit être rattaché à une caisse et à une session ouverte.")
    _ensure_same_entreprise(paiement.caisse, entreprise, "La caisse sélectionnée appartient à une autre entreprise.")
    _ensure_same_entreprise(paiement.session_caisse, entreprise, "La session de caisse appartient à une autre entreprise.")

    existing = MouvementCaisse.objects.filter(
        entreprise=entreprise,
        source_app="joatham_rh",
        source_model="PaiementSalaire",
        source_id=paiement.id,
    ).first()
    if existing is not None:
        paiement.caisse = existing.caisse
        paiement.session_caisse = existing.session
        paiement.mouvement_caisse = existing
        paiement.save(update_fields=["caisse", "session_caisse", "mouvement_caisse", "updated_at"])
        return existing

    mouvement = record_mouvement(
        entreprise=entreprise,
        caisse=paiement.caisse,
        session=paiement.session_caisse,
        type_mouvement=MouvementCaisse.TypeMouvement.SORTIE,
        montant=paiement.montant_paye,
        libelle=_build_paiement_salaire_cash_label(paiement),
        reference=_build_paiement_salaire_cash_reference(paiement),
        commentaire="Paiement de salaire enregistré depuis le module RH.",
        source_app="joatham_rh",
        source_model="PaiementSalaire",
        source_id=paiement.id,
        utilisateur=utilisateur,
        statut=MouvementCaisse.Statut.CONFIRME,
        moyen_paiement=_map_salary_payment_method_to_cash_method(paiement.mode_paiement),
    )
    paiement.mouvement_caisse = mouvement
    paiement.save(update_fields=["mouvement_caisse", "updated_at"])
    return mouvement


@transaction.atomic
def create_paiement_salaire(
    *,
    entreprise,
    employe,
    periode_mois,
    periode_annee,
    salaire_base=None,
    primes=0,
    retenues=0,
    montant_paye=0,
    date_paiement=None,
    mode_paiement=PaiementSalaire.ModePaiement.ESPECES,
    reference="",
    notes="",
    caisse=None,
    utilisateur=None,
):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    month = _normalize_period_month(periode_mois)
    year = _normalize_period_year(periode_annee)
    base_value = employe.salaire_base if salaire_base in {None, ""} else salaire_base
    salaire_base_amount = _normalize_non_negative_amount(base_value, "Le salaire de base est invalide.")
    primes_amount = _normalize_non_negative_amount(primes, "Le montant des primes est invalide.")
    retenues_amount = _normalize_non_negative_amount(retenues, "Le montant des retenues est invalide.")
    montant_paye_amount = _normalize_non_negative_amount(montant_paye, "Le montant paye est invalide.")
    caisse_obj = None
    session_caisse = None
    if montant_paye_amount > 0 and caisse not in {None, ""}:
        caisse_obj, session_caisse = _resolve_paiement_salaire_cashbox_context(
            entreprise=entreprise,
            caisse=caisse,
            utilisateur=utilisateur,
        )
    total_avances = get_total_avances_salaire_valides_du_mois(
        entreprise=entreprise,
        employe=employe,
        periode_mois=month,
        periode_annee=year,
    )
    net = calculer_net_salaire(
        salaire_base=salaire_base_amount,
        primes=primes_amount,
        retenues=retenues_amount,
        total_avances_deduites=total_avances,
    )
    paiement = PaiementSalaire.objects.create(
        entreprise=entreprise,
        employe=employe,
        periode_mois=month,
        periode_annee=year,
        salaire_base=salaire_base_amount,
        total_avances_deduites=total_avances,
        primes=primes_amount,
        retenues=retenues_amount,
        montant_net_a_payer=net,
        montant_paye=montant_paye_amount,
        date_paiement=_normalize_optional_date(date_paiement),
        mode_paiement=_validate_choice(mode_paiement, PaiementSalaire.ModePaiement.choices, "Le mode de paiement est invalide."),
        reference=(reference or "").strip(),
        notes=(notes or "").strip(),
        cree_par=utilisateur,
        caisse=caisse_obj,
        session_caisse=session_caisse,
    )
    if caisse_obj is not None:
        create_cash_movement_for_paiement_salaire(
            paiement=paiement,
            entreprise=entreprise,
            utilisateur=utilisateur,
        )
        paiement.refresh_from_db(fields=["caisse", "session_caisse", "mouvement_caisse", "updated_at"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="rh_paiement_salaire_created",
        module="rh",
        objet_type="PaiementSalaire",
        objet_id=paiement.id,
        description=f"Paiement salaire cree pour {employe.matricule} - {month:02d}/{year}.",
        metadata={
            "paiement_id": paiement.id,
            "employe_id": employe.id,
            "periode_mois": month,
            "periode_annee": year,
            "montant_net_a_payer": str(paiement.montant_net_a_payer),
            "montant_paye": str(paiement.montant_paye),
            "statut": paiement.statut,
            "caisse_id": paiement.caisse_id,
            "session_caisse_id": paiement.session_caisse_id,
            "mouvement_caisse_id": paiement.mouvement_caisse_id,
        },
    )
    return paiement
