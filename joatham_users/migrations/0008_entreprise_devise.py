from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_users", "0007_entreprise_logo"),
    ]

    operations = [
        migrations.AddField(
            model_name="entreprise",
            name="devise",
            field=models.CharField(
                choices=[
                    ("CDF", "Franc congolais"),
                    ("AOA", "Kwanza angolais"),
                    ("XAF", "Franc CFA"),
                    ("USD", "Dollar americain"),
                    ("EUR", "Euro"),
                ],
                default="CDF",
                max_length=10,
            ),
        ),
    ]
