from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_users", "0008_entreprise_devise"),
    ]

    operations = [
        migrations.AlterField(
            model_name="entreprise",
            name="devise",
            field=models.CharField(default="CDF", max_length=10),
        ),
    ]
