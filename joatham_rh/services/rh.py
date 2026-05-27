from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.audit import record_audit_event
from joatham_users.permissions import user_has_permission

from ..models import DemandeConge, DocumentRH, Employe, Poste, Presence


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
