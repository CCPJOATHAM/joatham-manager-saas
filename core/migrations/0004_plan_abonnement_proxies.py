from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_users", "0013_user_email_verified_user_email_verified_at"),
        ("core", "0003_paiementabonnement"),
    ]

    operations = [
        migrations.CreateModel(
            name="Plan",
            fields=[],
            options={
                "verbose_name": "Plan SaaS",
                "verbose_name_plural": "Plans SaaS",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("joatham_users.abonnement",),
        ),
        migrations.CreateModel(
            name="Abonnement",
            fields=[],
            options={
                "verbose_name": "Abonnement SaaS",
                "verbose_name_plural": "Abonnements SaaS",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("joatham_users.abonnemententreprise",),
        ),
    ]
