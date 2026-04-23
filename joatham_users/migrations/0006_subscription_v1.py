import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_users", "0005_user_role_proprietaire"),
    ]

    operations = [
        migrations.AddField(
            model_name="abonnement",
            name="actif",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="code",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.CreateModel(
            name="AbonnementEntreprise",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "statut",
                    models.CharField(
                        choices=[("essai", "Essai"), ("actif", "Actif"), ("expire", "Expire"), ("suspendu", "Suspendu")],
                        default="actif",
                        max_length=20,
                    ),
                ),
                ("date_debut", models.DateField()),
                ("date_fin", models.DateField()),
                ("essai", models.BooleanField(default=False)),
                ("actif", models.BooleanField(default=True)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                (
                    "entreprise",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="abonnement_entreprise",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="abonnements_entreprises",
                        to="joatham_users.abonnement",
                    ),
                ),
            ],
            options={"ordering": ["-date_creation", "-id"]},
        ),
    ]
