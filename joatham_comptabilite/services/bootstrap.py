from datetime import date

from ..models import CompteComptable, ExerciceComptable, JournalComptable


DEFAULT_COMPTES = [
    {"numero": "101", "nom": "Capital", "classe": "1", "categorie": "capitaux_propres", "sens_normal": "credit"},
    {"numero": "411", "nom": "Clients", "classe": "4", "categorie": "tiers", "sens_normal": "debit"},
    {"numero": "401", "nom": "Fournisseurs", "classe": "4", "categorie": "tiers", "sens_normal": "credit"},
    {"numero": "443", "nom": "TVA collectee", "classe": "4", "categorie": "fiscal", "sens_normal": "credit"},
    {"numero": "444", "nom": "TVA deductibile", "classe": "4", "categorie": "fiscal", "sens_normal": "debit"},
    {"numero": "521", "nom": "Banque", "classe": "5", "categorie": "tresorerie", "sens_normal": "debit"},
    {"numero": "531", "nom": "Caisse", "classe": "5", "categorie": "tresorerie", "sens_normal": "debit"},
    {"numero": "601", "nom": "Charges d'exploitation", "classe": "6", "categorie": "charge", "sens_normal": "debit"},
    {"numero": "701", "nom": "Ventes", "classe": "7", "categorie": "produit", "sens_normal": "credit"},
]


DEFAULT_JOURNAUX = [
    {"code": "JV", "nom": "Journal des ventes", "type_journal": "ventes"},
    {"code": "JA", "nom": "Journal des achats", "type_journal": "achats"},
    {"code": "TR", "nom": "Journal de tresorerie", "type_journal": "tresorerie"},
    {"code": "OD", "nom": "Operations diverses", "type_journal": "od"},
]


def bootstrap_comptabilite_entreprise(entreprise):
    today = date.today()
    exercice_code = f"EX-{today.year}"
    ExerciceComptable.objects.get_or_create(
        entreprise=entreprise,
        code=exercice_code,
        defaults={
            "date_debut": date(today.year, 1, 1),
            "date_fin": date(today.year, 12, 31),
            "statut": ExerciceComptable.Statut.OUVERT,
        },
    )

    for compte in DEFAULT_COMPTES:
        CompteComptable.objects.get_or_create(
            entreprise=entreprise,
            numero=compte["numero"],
            defaults=compte,
        )

    for journal in DEFAULT_JOURNAUX:
        JournalComptable.objects.get_or_create(
            entreprise=entreprise,
            code=journal["code"],
            defaults=journal,
        )
