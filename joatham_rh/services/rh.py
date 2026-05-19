from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_date

from core.audit import record_audit_event

from ..models import Employe, Poste, Presence


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


@transaction.atomic
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
    utilisateur=None,
):
    _ensure_same_entreprise(poste, entreprise, "Le poste selectionne appartient a une autre entreprise.")
    employe = Employe(
        entreprise=entreprise,
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

    try:
        employe.save()
    except IntegrityError as exc:
        raise RhOperationError("Un employe avec ce matricule existe deja pour cette entreprise.") from exc

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
    return employe


@transaction.atomic
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
    utilisateur=None,
):
    _ensure_same_entreprise(employe, entreprise, "L'employe selectionne appartient a une autre entreprise.")
    _ensure_same_entreprise(poste, entreprise, "Le poste selectionne appartient a une autre entreprise.")
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
        employe.save()
    except IntegrityError as exc:
        raise RhOperationError("Un employe avec ce matricule existe deja pour cette entreprise.") from exc

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
