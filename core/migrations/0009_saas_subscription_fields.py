from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_platformsettings_maintenance_modules"),
    ]

    operations = [
        migrations.AddField(
            model_name="paiementabonnement",
            name="date_paiement",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="methode_paiement",
            field=models.CharField(
                choices=[
                    ("manuel", "Manuel"),
                    ("mobile_money", "Mobile Money"),
                    ("carte", "Carte"),
                    ("virement", "Virement"),
                ],
                default="manuel",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="periode_debut",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="periode_fin",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="provider_reference",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="duree_essai_jours",
            field=models.PositiveIntegerField(default=14),
        ),
        migrations.AlterField(
            model_name="paiementabonnement",
            name="statut",
            field=models.CharField(
                choices=[
                    ("en_attente", "En attente"),
                    ("valide", "Valide"),
                    ("refuse", "Refuse"),
                    ("annule", "Annule"),
                ],
                default="en_attente",
                max_length=20,
            ),
        ),
    ]
