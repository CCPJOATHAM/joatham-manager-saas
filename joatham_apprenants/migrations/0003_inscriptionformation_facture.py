from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_billing", "0002_facture_workflow_and_payments"),
        ("joatham_apprenants", "0002_paiementinscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="inscriptionformation",
            name="facture",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="inscriptions_formations",
                to="joatham_billing.facture",
            ),
        ),
    ]
