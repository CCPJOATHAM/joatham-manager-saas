from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_billing", "0005_lignefacture_produit_tva"),
    ]

    operations = [
        migrations.AddField(
            model_name="lignefacture",
            name="service",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lignes_facture",
                to="joatham_billing.service",
            ),
        ),
    ]
