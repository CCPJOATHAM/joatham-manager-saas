from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_plan_abonnement_proxies"),
    ]

    operations = [
        migrations.AddField(
            model_name="paiementabonnement",
            name="devise_entreprise",
            field=models.CharField(default="USD", max_length=10),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="montant_devise_locale_estime",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="montant_usd",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="notes_validation",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="source_taux",
            field=models.CharField(default="manuel", max_length=30),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="taux_change_reference",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="telephone_paiement",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
