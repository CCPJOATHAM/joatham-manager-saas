from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_billing", "0003_alter_facture_tva"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="actif",
            field=models.BooleanField(default=True),
        ),
    ]
