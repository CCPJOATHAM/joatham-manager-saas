from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_paiementabonnement_cash_method"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paiementabonnement",
            name="duree",
            field=models.CharField(
                choices=[
                    ("mensuel", "Mensuel"),
                    ("trimestriel", "Trimestriel"),
                    ("semestriel", "Semestriel"),
                    ("annuel", "Annuel"),
                ],
                max_length=20,
            ),
        ),
    ]
