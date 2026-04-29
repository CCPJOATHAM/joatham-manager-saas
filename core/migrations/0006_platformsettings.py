from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_subscription_payment_v1_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom_plateforme", models.CharField(default="JOATHAM Manager", max_length=120)),
                ("email_systeme", models.EmailField(default="admin@joatham.com", max_length=254)),
                ("devise_defaut", models.CharField(default="CDF", max_length=10)),
                ("mode_maintenance", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Parametres plateforme",
                "verbose_name_plural": "Parametres plateforme",
            },
        ),
    ]
