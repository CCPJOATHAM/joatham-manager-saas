from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_paiementabonnement_automatic_payment_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="paiementabonnement",
            name="provider_notify_token",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
