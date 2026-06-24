from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def sync_inscription_financial_totals(apps, schema_editor):
    InscriptionFormation = apps.get_model("joatham_apprenants", "InscriptionFormation")
    PaiementInscription = apps.get_model("joatham_apprenants", "PaiementInscription")

    for inscription in InscriptionFormation.objects.all().iterator():
        paiements_total = (
            PaiementInscription.objects.filter(inscription_id=inscription.id).aggregate(total=Sum("montant"))["total"]
            or Decimal("0.00")
        )
        ancien_montant_paye = Decimal(str(inscription.montant_paye or 0))

        if ancien_montant_paye > paiements_total:
            PaiementInscription.objects.create(
                entreprise_id=inscription.entreprise_id,
                inscription_id=inscription.id,
                montant=ancien_montant_paye - paiements_total,
                mode_paiement="autre",
                observations="Paiement historique migré depuis l'ancien montant payé.",
            )
            paiements_total = ancien_montant_paye

        solde = max(Decimal(str(inscription.montant_prevu or 0)) - paiements_total, Decimal("0.00"))
        InscriptionFormation.objects.filter(id=inscription.id).update(
            montant_paye=paiements_total,
            solde=solde,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_apprenants", "0003_inscriptionformation_facture"),
    ]

    operations = [
        migrations.RunPython(sync_inscription_financial_totals, migrations.RunPython.noop),
    ]
