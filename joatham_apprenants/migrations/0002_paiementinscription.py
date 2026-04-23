from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_apprenants", "0001_initial"),
        ("joatham_users", "0005_user_role_proprietaire"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaiementInscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("montant", models.DecimalField(decimal_places=2, max_digits=10)),
                ("date_paiement", models.DateField(default=django.utils.timezone.now)),
                (
                    "mode_paiement",
                    models.CharField(
                        choices=[
                            ("especes", "Especes"),
                            ("virement", "Virement"),
                            ("mobile_money", "Mobile Money"),
                            ("cheque", "Cheque"),
                            ("autre", "Autre"),
                        ],
                        default="especes",
                        max_length=20,
                    ),
                ),
                ("reference", models.CharField(blank=True, default="", max_length=100)),
                ("observations", models.TextField(blank=True, default="")),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paiements_inscriptions",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "inscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paiements",
                        to="joatham_apprenants.inscriptionformation",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="paiements_apprenants",
                        to="joatham_users.user",
                    ),
                ),
            ],
            options={"ordering": ["-date_paiement", "-date_creation", "-id"]},
        ),
    ]
