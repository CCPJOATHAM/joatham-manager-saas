from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_billing", "0008_paiementfacture_caisse_session_caisse"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paiementfacture",
            name="mode",
            field=models.CharField(
                choices=[
                    ("especes", "Especes"),
                    ("virement", "Virement"),
                    ("mobile_money", "Mobile Money"),
                    ("mpesa", "M-Pesa"),
                    ("orange_money", "Orange Money"),
                    ("airtel_money", "Airtel Money"),
                    ("afrimoney", "Afrimoney"),
                    ("carte", "Carte bancaire"),
                    ("cheque", "Cheque"),
                    ("autre", "Autre"),
                ],
                default="especes",
                max_length=20,
            ),
        ),
    ]

