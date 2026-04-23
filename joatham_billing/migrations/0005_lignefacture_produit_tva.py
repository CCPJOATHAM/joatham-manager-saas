from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_products", "0002_produit_description"),
        ("joatham_billing", "0004_service_actif"),
    ]

    operations = [
        migrations.AddField(
            model_name="lignefacture",
            name="produit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lignes_facture",
                to="joatham_products.produit",
            ),
        ),
        migrations.AddField(
            model_name="lignefacture",
            name="tva",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]
