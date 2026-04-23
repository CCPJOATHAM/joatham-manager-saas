from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_users", "0006_subscription_v1"),
    ]

    operations = [
        migrations.AddField(
            model_name="entreprise",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="entreprises/logos/"),
        ),
    ]
