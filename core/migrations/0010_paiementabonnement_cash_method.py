from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_saas_subscription_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paiementabonnement",
            name="methode_paiement",
            field=models.CharField(
                choices=[
                    ("manuel", "Manuel"),
                    ("mobile_money", "Mobile Money"),
                    ("carte", "Carte"),
                    ("virement", "Virement"),
                    ("cash", "Cash"),
                ],
                default="manuel",
                max_length=30,
            ),
        ),
    ]
