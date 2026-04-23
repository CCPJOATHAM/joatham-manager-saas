from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch

from core.audit import record_audit_event
from joatham_billing.models import Facture, PaiementFacture
from joatham_depenses.models import Depense

from ..models import (
    CompteComptable,
    EcritureComptable,
    ExerciceComptable,
    JournalComptable,
    LigneEcritureComptable,
)


def get_open_exercice(entreprise, date_piece):
    exercice = ExerciceComptable.objects.filter(
        entreprise=entreprise,
        statut=ExerciceComptable.Statut.OUVERT,
        date_debut__lte=date_piece,
        date_fin__gte=date_piece,
    ).first()
    if not exercice:
        raise ValidationError("Aucun exercice comptable ouvert pour cette date.")
    return exercice


def get_compte(entreprise, numero):
    return CompteComptable.objects.get(entreprise=entreprise, numero=numero, actif=True)


def get_journal(entreprise, code):
    return JournalComptable.objects.get(entreprise=entreprise, code=code, actif=True)


def get_ecriture_source_queryset():
    return EcritureComptable.objects.select_related("entreprise", "journal", "exercice").prefetch_related(
        Prefetch("lignes", queryset=LigneEcritureComptable.objects.select_related("compte").order_by("id"))
    )


@transaction.atomic
def create_balanced_entry(
    *,
    entreprise,
    journal,
    numero_piece,
    date_piece,
    libelle,
    lignes,
    source_app,
    source_model,
    source_id,
    source_event,
):
    existing = EcritureComptable.objects.filter(
        entreprise=entreprise,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
        source_event=source_event,
    ).first()
    if existing:
        return existing

    total_debit = sum((Decimal(ligne["debit"]) for ligne in lignes), Decimal("0"))
    total_credit = sum((Decimal(ligne["credit"]) for ligne in lignes), Decimal("0"))
    if total_debit != total_credit:
        raise ValidationError("L'ecriture comptable n'est pas equilibree.")

    exercice = get_open_exercice(entreprise, date_piece)
    ecriture = EcritureComptable.objects.create(
        entreprise=entreprise,
        exercice=exercice,
        journal=journal,
        numero_piece=numero_piece,
        date_piece=date_piece,
        libelle=libelle,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
        source_event=source_event,
        statut=EcritureComptable.Statut.VALIDE,
    )

    for ligne in lignes:
        LigneEcritureComptable.objects.create(
            ecriture=ecriture,
            compte=ligne["compte"],
            libelle=ligne.get("libelle", ""),
            debit=ligne["debit"],
            credit=ligne["credit"],
        )

    if not ecriture.est_equilibree():
        raise ValidationError("L'ecriture creee n'est pas equilibree.")

    record_audit_event(
        entreprise=entreprise,
        utilisateur=None,
        action="ecriture_comptable_creee",
        module="comptabilite",
        objet_type="EcritureComptable",
        objet_id=ecriture.id,
        description=f"Ecriture comptable creee: {ecriture.numero_piece}.",
        metadata={"journal": journal.code, "source_model": source_model, "source_event": source_event},
    )
    return ecriture


@transaction.atomic
def comptabiliser_facture_emise(facture: Facture):
    if facture.statut not in {Facture.Statut.EMISE, Facture.Statut.PAYEE}:
        return None

    journal = get_journal(facture.entreprise, "JV")
    compte_client = get_compte(facture.entreprise, "411")
    compte_vente = get_compte(facture.entreprise, "701")
    compte_tva = get_compte(facture.entreprise, "443")

    lignes = [
        {"compte": compte_client, "debit": facture.total_net, "credit": Decimal("0"), "libelle": facture.libelle if hasattr(facture, "libelle") else facture.numero},
        {"compte": compte_vente, "debit": Decimal("0"), "credit": facture.total_ht, "libelle": "Vente facture"},
    ]
    if facture.total_tva > Decimal("0"):
        lignes.append({"compte": compte_tva, "debit": Decimal("0"), "credit": facture.total_tva, "libelle": "TVA collectee"})

    return create_balanced_entry(
        entreprise=facture.entreprise,
        journal=journal,
        numero_piece=facture.numero,
        date_piece=facture.date.date(),
        libelle=f"Facture {facture.numero}",
        lignes=lignes,
        source_app="joatham_billing",
        source_model="Facture",
        source_id=facture.id,
        source_event="facture_emise",
    )


@transaction.atomic
def comptabiliser_paiement_facture(paiement: PaiementFacture):
    if paiement.statut != PaiementFacture.StatutPaiement.VALIDE:
        return None

    facture = paiement.facture
    journal = get_journal(facture.entreprise, "TR")
    compte_client = get_compte(facture.entreprise, "411")
    compte_tresorerie = get_compte(
        facture.entreprise,
        "521" if paiement.mode in {PaiementFacture.ModePaiement.VIREMENT, PaiementFacture.ModePaiement.CHEQUE, PaiementFacture.ModePaiement.MOBILE_MONEY} else "531",
    )

    return create_balanced_entry(
        entreprise=facture.entreprise,
        journal=journal,
        numero_piece=f"{facture.numero}-PAY-{paiement.id}",
        date_piece=paiement.date_paiement.date(),
        libelle=f"Paiement facture {facture.numero}",
        lignes=[
            {"compte": compte_tresorerie, "debit": paiement.montant, "credit": Decimal("0"), "libelle": "Encaissement"},
            {"compte": compte_client, "debit": Decimal("0"), "credit": paiement.montant, "libelle": "Lettrage client"},
        ],
        source_app="joatham_billing",
        source_model="PaiementFacture",
        source_id=paiement.id,
        source_event="paiement_facture",
    )


@transaction.atomic
def comptabiliser_depense(depense: Depense):
    journal = get_journal(depense.entreprise, "JA")
    compte_charge = get_compte(depense.entreprise, "601")
    compte_tresorerie = get_compte(depense.entreprise, "531")

    return create_balanced_entry(
        entreprise=depense.entreprise,
        journal=journal,
        numero_piece=f"DEP-{depense.id}",
        date_piece=depense.date.date(),
        libelle=f"Depense {depense.description}",
        lignes=[
            {"compte": compte_charge, "debit": depense.montant, "credit": Decimal("0"), "libelle": depense.description},
            {"compte": compte_tresorerie, "debit": Decimal("0"), "credit": depense.montant, "libelle": "Sortie caisse"},
        ],
        source_app="joatham_depenses",
        source_model="Depense",
        source_id=depense.id,
        source_event="depense_validee",
    )
