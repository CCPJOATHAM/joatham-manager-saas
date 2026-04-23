from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from ..models import EcritureComptable
from ..selectors.comptabilite import (
    get_lignes_ecriture_before_date_by_entreprise,
    get_lignes_ecriture_by_entreprise,
)


ZERO = Decimal("0.00")

ASSET_CLASSES = {"2", "3", "5"}
LIABILITY_CLASSES = {"1"}

REPORT_TITLES = {
    "balance": "Balance comptable",
    "grand_livre": "Grand livre",
    "compte_resultat": "Compte de resultat",
    "bilan": "Bilan simplifie",
}


def _normalize_period(date_debut=None, date_fin=None):
    if date_debut and date_fin and date_debut > date_fin:
        return date_fin, date_debut
    return date_debut, date_fin


def _quantize(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _build_period_label(date_debut=None, date_fin=None):
    if date_debut and date_fin:
        return f"Du {date_debut:%d/%m/%Y} au {date_fin:%d/%m/%Y}"
    if date_debut:
        return f"A partir du {date_debut:%d/%m/%Y}"
    if date_fin:
        return f"Jusqu'au {date_fin:%d/%m/%Y}"
    return "Toutes periodes"


def get_lignes_queryset(entreprise, date_debut=None, date_fin=None):
    date_debut, date_fin = _normalize_period(date_debut, date_fin)
    queryset = get_lignes_ecriture_by_entreprise(
        entreprise,
        date_debut=date_debut,
        date_fin=date_fin,
        statut=EcritureComptable.Statut.VALIDE,
    )
    return queryset


def _get_opening_queryset(entreprise, date_debut=None):
    return get_lignes_ecriture_before_date_by_entreprise(
        entreprise,
        date_debut,
        statut=EcritureComptable.Statut.VALIDE,
    )


def _empty_account_bucket(compte):
    return {
        "compte": compte,
        "numero": compte.numero,
        "nom": compte.nom,
        "classe": compte.classe,
        "categorie": compte.categorie,
        "sens_normal": compte.sens_normal,
        "debit": ZERO,
        "credit": ZERO,
    }


def _group_account_totals(lignes):
    grouped = {}
    for ligne in lignes:
        bucket = grouped.setdefault(ligne.compte_id, _empty_account_bucket(ligne.compte))
        bucket["debit"] += _quantize(ligne.debit)
        bucket["credit"] += _quantize(ligne.credit)
    return dict(sorted(grouped.items(), key=lambda item: item[1]["numero"]))


def _split_balance(net_amount):
    if net_amount >= ZERO:
        return _quantize(net_amount), ZERO
    return ZERO, _quantize(-net_amount)


def build_balance(entreprise, date_debut=None, date_fin=None):
    lignes = list(get_lignes_queryset(entreprise, date_debut=date_debut, date_fin=date_fin))
    grouped = _group_account_totals(lignes)

    rows = []
    total_debit = ZERO
    total_credit = ZERO
    total_solde_debit = ZERO
    total_solde_credit = ZERO

    for item in grouped.values():
        debit = _quantize(item["debit"])
        credit = _quantize(item["credit"])
        solde_debit, solde_credit = _split_balance(debit - credit)
        total_debit += debit
        total_credit += credit
        total_solde_debit += solde_debit
        total_solde_credit += solde_credit
        rows.append(
            {
                "compte": item["compte"],
                "numero": item["numero"],
                "nom": item["nom"],
                "debit": debit,
                "credit": credit,
                "solde_debit": solde_debit,
                "solde_credit": solde_credit,
            }
        )

    return {
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "total_solde_debit": total_solde_debit,
        "total_solde_credit": total_solde_credit,
        "period_label": _build_period_label(date_debut, date_fin),
        "generated_at": timezone.localtime(timezone.now()),
    }


def build_grand_livre(entreprise, date_debut=None, date_fin=None):
    date_debut, date_fin = _normalize_period(date_debut, date_fin)
    opening_grouped = _group_account_totals(_get_opening_queryset(entreprise, date_debut))
    lignes = list(get_lignes_queryset(entreprise, date_debut=date_debut, date_fin=date_fin))

    accounts = []
    current_account = None
    current_account_id = None

    for ligne in lignes:
        if current_account_id != ligne.compte_id:
            opening = opening_grouped.get(ligne.compte_id, _empty_account_bucket(ligne.compte))
            opening_balance = _quantize(opening["debit"] - opening["credit"])
            ouverture_debit, ouverture_credit = _split_balance(opening_balance)
            current_account = {
                "compte": ligne.compte,
                "numero": ligne.compte.numero,
                "nom": ligne.compte.nom,
                "ouverture_debit": ouverture_debit,
                "ouverture_credit": ouverture_credit,
                "lignes": [],
                "total_debit": ZERO,
                "total_credit": ZERO,
                "solde_debit": ZERO,
                "solde_credit": ZERO,
                "solde_courant": opening_balance,
            }
            accounts.append(current_account)
            current_account_id = ligne.compte_id

        debit = _quantize(ligne.debit)
        credit = _quantize(ligne.credit)
        current_account["total_debit"] += debit
        current_account["total_credit"] += credit
        current_account["solde_courant"] = _quantize(current_account["solde_courant"] + debit - credit)
        cumul_debit, cumul_credit = _split_balance(current_account["solde_courant"])
        current_account["lignes"].append(
            {
                "date_piece": ligne.ecriture.date_piece,
                "journal": ligne.ecriture.journal.code,
                "numero_piece": ligne.ecriture.numero_piece,
                "libelle": ligne.libelle or ligne.ecriture.libelle,
                "debit": debit,
                "credit": credit,
                "solde_debit": cumul_debit,
                "solde_credit": cumul_credit,
            }
        )

    for account in accounts:
        solde_final = _quantize(account["ouverture_debit"] - account["ouverture_credit"] + account["total_debit"] - account["total_credit"])
        account["solde_debit"], account["solde_credit"] = _split_balance(solde_final)
        del account["solde_courant"]

    return {
        "accounts": accounts,
        "period_label": _build_period_label(date_debut, date_fin),
        "generated_at": timezone.localtime(timezone.now()),
    }


def build_compte_resultat(entreprise, date_debut=None, date_fin=None):
    lignes = list(get_lignes_queryset(entreprise, date_debut=date_debut, date_fin=date_fin))
    grouped = _group_account_totals(lignes)

    produits = []
    charges = []

    for item in grouped.values():
        numero = item["numero"]
        if numero.startswith("7"):
            montant = _quantize(item["credit"] - item["debit"])
            if montant:
                produits.append(
                    {
                        "compte": item["compte"],
                        "numero": numero,
                        "nom": item["nom"],
                        "montant": montant,
                    }
                )
        elif numero.startswith("6"):
            montant = _quantize(item["debit"] - item["credit"])
            if montant:
                charges.append(
                    {
                        "compte": item["compte"],
                        "numero": numero,
                        "nom": item["nom"],
                        "montant": montant,
                    }
                )

    total_produits = sum((row["montant"] for row in produits), ZERO)
    total_charges = sum((row["montant"] for row in charges), ZERO)
    resultat_net = _quantize(total_produits - total_charges)

    return {
        "produits": produits,
        "charges": charges,
        "total_produits": _quantize(total_produits),
        "total_charges": _quantize(total_charges),
        "resultat_net": resultat_net,
        "resultat_label": "Benefice" if resultat_net > ZERO else "Perte" if resultat_net < ZERO else "Equilibre",
        "period_label": _build_period_label(date_debut, date_fin),
        "generated_at": timezone.localtime(timezone.now()),
    }


def build_bilan_simplifie(entreprise, date_debut=None, date_fin=None):
    lignes = list(get_lignes_queryset(entreprise, date_debut=date_debut, date_fin=date_fin))
    grouped = _group_account_totals(lignes)

    actif_sections = defaultdict(list)
    passif_sections = defaultdict(list)

    for item in grouped.values():
        net = _quantize(item["debit"] - item["credit"])
        numero = item["numero"]
        classe = item["classe"]

        if classe in ASSET_CLASSES and net > ZERO:
            actif_sections["Actif"].append({"numero": numero, "nom": item["nom"], "montant": net})
        elif classe == "5" and net < ZERO:
            passif_sections["Dettes de tresorerie"].append(
                {"numero": numero, "nom": item["nom"], "montant": _quantize(-net)}
            )
        elif classe in LIABILITY_CLASSES and net < ZERO:
            passif_sections["Capitaux propres"].append({"numero": numero, "nom": item["nom"], "montant": _quantize(-net)})
        elif classe == "4":
            if net > ZERO:
                actif_sections["Tiers et creances"].append({"numero": numero, "nom": item["nom"], "montant": net})
            elif net < ZERO:
                passif_sections["Dettes"].append({"numero": numero, "nom": item["nom"], "montant": _quantize(-net)})

    compte_resultat = build_compte_resultat(entreprise, date_debut=date_debut, date_fin=date_fin)
    resultat_net = compte_resultat["resultat_net"]
    if resultat_net > ZERO:
        passif_sections["Resultat de la periode"].append(
            {"numero": "12", "nom": "Resultat net beneficiaire", "montant": resultat_net}
        )
    elif resultat_net < ZERO:
        actif_sections["Resultat de la periode"].append(
            {"numero": "12", "nom": "Resultat net deficit", "montant": _quantize(-resultat_net)}
        )

    actif = []
    passif = []

    total_actif = ZERO
    total_passif = ZERO

    for label in ["Actif", "Tiers et creances", "Resultat de la periode"]:
        rows = actif_sections.get(label, [])
        subtotal = sum((row["montant"] for row in rows), ZERO)
        if rows:
            actif.append({"label": label, "rows": rows, "subtotal": _quantize(subtotal)})
            total_actif += subtotal

    for label in ["Capitaux propres", "Dettes", "Dettes de tresorerie", "Resultat de la periode"]:
        rows = passif_sections.get(label, [])
        subtotal = sum((row["montant"] for row in rows), ZERO)
        if rows:
            passif.append({"label": label, "rows": rows, "subtotal": _quantize(subtotal)})
            total_passif += subtotal

    return {
        "actif_sections": actif,
        "passif_sections": passif,
        "actif": _quantize(total_actif),
        "passif": _quantize(total_passif),
        "equilibre": _quantize(total_actif - total_passif) == ZERO,
        "period_label": _build_period_label(date_debut, date_fin),
        "generated_at": timezone.localtime(timezone.now()),
    }


def build_dashboard(entreprise, date_debut=None, date_fin=None):
    balance = build_balance(entreprise, date_debut=date_debut, date_fin=date_fin)
    compte_resultat = build_compte_resultat(entreprise, date_debut=date_debut, date_fin=date_fin)
    bilan = build_bilan_simplifie(entreprise, date_debut=date_debut, date_fin=date_fin)
    grand_livre = build_grand_livre(entreprise, date_debut=date_debut, date_fin=date_fin)

    return {
        "balance_preview": balance["rows"][:5],
        "grand_livre_preview": grand_livre["accounts"][:3],
        "produits": compte_resultat["total_produits"],
        "charges": compte_resultat["total_charges"],
        "resultat": compte_resultat["resultat_net"],
        "resultat_label": compte_resultat["resultat_label"],
        "total_debit": balance["total_debit"],
        "total_credit": balance["total_credit"],
        "actif": bilan["actif"],
        "passif": bilan["passif"],
        "equilibre_bilan": bilan["equilibre"],
        "period_label": _build_period_label(date_debut, date_fin),
        "generated_at": timezone.localtime(timezone.now()),
    }


def build_report_payload(report_slug, entreprise, date_debut=None, date_fin=None):
    builders = {
        "balance": build_balance,
        "grand_livre": build_grand_livre,
        "compte_resultat": build_compte_resultat,
        "bilan": build_bilan_simplifie,
    }
    if report_slug not in builders:
        raise ValueError(f"Rapport inconnu: {report_slug}")

    data = builders[report_slug](entreprise, date_debut=date_debut, date_fin=date_fin)
    return {
        "report_slug": report_slug,
        "report_title": REPORT_TITLES[report_slug],
        "report": data,
    }
