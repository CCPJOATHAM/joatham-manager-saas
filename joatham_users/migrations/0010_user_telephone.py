from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_users", "0009_alter_entreprise_devise"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="telephone",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
    ]
