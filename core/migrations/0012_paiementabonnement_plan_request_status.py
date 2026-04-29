from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_paiementabonnement_semestriel_duration"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paiementabonnement",
            name="statut",
            field=models.CharField(
                choices=[
                    ("en_attente", "En attente"),
                    ("approuvee", "Approuvee"),
                    ("valide", "Valide"),
                    ("refuse", "Refuse"),
                    ("annule", "Annule"),
                ],
                default="en_attente",
                max_length=20,
            ),
        ),
    ]
