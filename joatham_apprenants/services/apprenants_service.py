from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from core.audit import record_audit_event
from core.services.tenancy import ensure_same_entreprise, get_object_for_entreprise

from ..models import Apprenant, Formation, InscriptionFormation, PaiementInscription


def create_apprenant(
    *,
    entreprise,
    nom,
    prenom="",
    telephone="",
    email="",
    adresse="",
    date_inscription=None,
    actif=True,
    observations="",
    utilisateur=None,
):
    apprenant_data = {
        "entreprise": entreprise,
        "nom": (nom or "").strip(),
        "prenom": (prenom or "").strip(),
        "telephone": (telephone or "").strip(),
        "email": (email or "").strip(),
        "adresse": (adresse or "").strip(),
        "actif": actif,
        "observations": (observations or "").strip(),
    }
    if date_inscription is not None:
        apprenant_data["date_inscription"] = date_inscription

    apprenant = Apprenant.objects.create(**apprenant_data)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="creation_apprenant",
        module="apprenants",
        objet_type="Apprenant",
        objet_id=apprenant.id,
        description=f"Apprenant cree: {apprenant}.",
        metadata={"email": apprenant.email, "telephone": apprenant.telephone},
    )
    return apprenant


def create_formation(
    *,
    entreprise,
    nom,
    description="",
    prix=Decimal("0.00"),
    duree="",
    actif=True,
    utilisateur=None,
):
    formation = Formation.objects.create(
        entreprise=entreprise,
        nom=(nom or "").strip(),
        description=(description or "").strip(),
        prix=Decimal(str(prix or 0)),
        duree=(duree or "").strip(),
        actif=actif,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="formation_creee",
        module="apprenants",
        objet_type="Formation",
        objet_id=formation.id,
        description=f"Formation creee: {formation.nom}.",
        metadata={"prix": str(formation.prix), "actif": formation.actif},
    )
    return formation


def update_formation(
    formation,
    *,
    nom,
    description="",
    prix=Decimal("0.00"),
    duree="",
    actif=True,
    utilisateur=None,
):
    formation.nom = (nom or "").strip()
    formation.description = (description or "").strip()
    formation.prix = Decimal(str(prix or 0))
    formation.duree = (duree or "").strip()
    formation.actif = actif
    formation.save()
    record_audit_event(
        entreprise=formation.entreprise,
        utilisateur=utilisateur,
        action="formation_modifiee",
        module="apprenants",
        objet_type="Formation",
        objet_id=formation.id,
        description=f"Formation modifiee: {formation.nom}.",
        metadata={"prix": str(formation.prix), "actif": formation.actif},
    )
    return formation


def toggle_formation_active(formation, *, actif, utilisateur=None):
    formation.actif = actif
    formation.save(update_fields=["actif"])
    record_audit_event(
        entreprise=formation.entreprise,
        utilisateur=utilisateur,
        action="formation_statut_modifie",
        module="apprenants",
        objet_type="Formation",
        objet_id=formation.id,
        description=f"Formation {'activee' if actif else 'desactivee'}: {formation.nom}.",
        metadata={"actif": formation.actif},
    )
    return formation


def inscrire_apprenant_a_formation(
    *,
    entreprise,
    apprenant_id,
    formation_id,
    date_inscription=None,
    statut=InscriptionFormation.Statut.EN_COURS,
    montant_prevu=None,
    montant_paye=Decimal("0.00"),
    utilisateur=None,
):
    apprenant = get_object_for_entreprise(Apprenant.objects.all(), entreprise, id=apprenant_id)
    formation = get_object_for_entreprise(Formation.objects.all(), entreprise, id=formation_id)

    ensure_same_entreprise(apprenant, entreprise)
    ensure_same_entreprise(formation, entreprise)

    montant_prevu_value = (
        Decimal(str(montant_prevu)) if montant_prevu not in (None, "") else Decimal(str(formation.prix or 0))
    )
    montant_paye_value = Decimal(str(montant_paye or 0))

    inscription_data = {
        "entreprise": entreprise,
        "apprenant": apprenant,
        "formation": formation,
        "statut": statut,
        "montant_prevu": montant_prevu_value,
        "montant_paye": montant_paye_value,
    }
    if date_inscription is not None:
        inscription_data["date_inscription"] = date_inscription

    with transaction.atomic():
        inscription = InscriptionFormation.objects.create(**inscription_data)

        if montant_paye_value > Decimal("0.00"):
            PaiementInscription.objects.create(
                entreprise=entreprise,
                inscription=inscription,
                montant=montant_paye_value,
                mode_paiement=PaiementInscription.ModePaiement.AUTRE,
                observations="Paiement initial enregistre lors de l'inscription.",
                utilisateur=utilisateur,
            )

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="inscription_formation_creee",
        module="apprenants",
        objet_type="InscriptionFormation",
        objet_id=inscription.id,
        description=f"Inscription creee pour {apprenant} a la formation {formation}.",
        metadata={
            "apprenant_id": apprenant.id,
            "formation_id": formation.id,
            "montant_prevu": str(inscription.montant_prevu),
            "montant_paye": str(inscription.montant_paye),
            "solde": str(inscription.solde),
        },
    )
    return inscription


def recalculate_inscription_totals(inscription, *, baseline_montant_paye=Decimal("0.00")):
    montant_paye = (
        inscription.paiements.aggregate(total=Sum("montant"))["total"]
        or Decimal("0.00")
    )
    inscription.montant_paye = Decimal(str(montant_paye)) + Decimal(str(baseline_montant_paye or 0))
    inscription.solde = Decimal(str(inscription.montant_prevu or 0)) - inscription.montant_paye
    inscription.save(update_fields=["montant_paye", "solde"])
    return inscription


@transaction.atomic
def create_paiement_inscription(
    *,
    entreprise,
    inscription_id,
    montant,
    date_paiement=None,
    mode_paiement=PaiementInscription.ModePaiement.ESPECES,
    reference="",
    observations="",
    utilisateur=None,
):
    inscription = get_object_for_entreprise(
        InscriptionFormation.objects.select_for_update(),
        entreprise,
        id=inscription_id,
    )
    ensure_same_entreprise(inscription, entreprise)
    paiements_existants = inscription.paiements.aggregate(total=Sum("montant"))["total"] or Decimal("0.00")
    baseline_montant_paye = Decimal(str(inscription.montant_paye or 0)) - Decimal(str(paiements_existants))
    if baseline_montant_paye < Decimal("0.00"):
        baseline_montant_paye = Decimal("0.00")

    paiement_data = {
        "entreprise": entreprise,
        "inscription": inscription,
        "montant": Decimal(str(montant or 0)),
        "mode_paiement": mode_paiement or PaiementInscription.ModePaiement.ESPECES,
        "reference": (reference or "").strip(),
        "observations": (observations or "").strip(),
        "utilisateur": utilisateur,
    }
    if date_paiement is not None:
        paiement_data["date_paiement"] = date_paiement

    paiement = PaiementInscription.objects.create(**paiement_data)
    inscription.refresh_from_db()
    recalculate_inscription_totals(inscription, baseline_montant_paye=baseline_montant_paye)

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="paiement_inscription_cree",
        module="apprenants",
        objet_type="PaiementInscription",
        objet_id=paiement.id,
        description=f"Paiement enregistre pour {inscription.apprenant} sur {inscription.formation}.",
        metadata={
            "inscription_id": inscription.id,
            "montant": str(paiement.montant),
            "mode_paiement": paiement.mode_paiement,
            "reference": paiement.reference,
        },
    )
    return paiement
