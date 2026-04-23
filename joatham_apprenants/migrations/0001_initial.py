from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("joatham_users", "0005_user_role_proprietaire"),
    ]

    operations = [
        migrations.CreateModel(
            name="Apprenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=100)),
                ("prenom", models.CharField(blank=True, default="", max_length=100)),
                ("telephone", models.CharField(blank=True, default="", max_length=30)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("adresse", models.CharField(blank=True, default="", max_length=255)),
                ("date_inscription", models.DateField(default=django.utils.timezone.now)),
                ("actif", models.BooleanField(default=True)),
                ("observations", models.TextField(blank=True, default="")),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="apprenants",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={"ordering": ["nom", "prenom", "id"]},
        ),
        migrations.CreateModel(
            name="Formation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=150)),
                ("description", models.TextField(blank=True, default="")),
                ("prix", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("duree", models.CharField(blank=True, default="", max_length=100)),
                ("actif", models.BooleanField(default=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="formations",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={"ordering": ["nom", "id"]},
        ),
        migrations.CreateModel(
            name="InscriptionFormation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date_inscription", models.DateField(default=django.utils.timezone.now)),
                (
                    "statut",
                    models.CharField(
                        choices=[("en_cours", "En cours"), ("terminee", "Terminee"), ("annulee", "Annulee")],
                        default="en_cours",
                        max_length=20,
                    ),
                ),
                ("montant_prevu", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("montant_paye", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("solde", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                (
                    "apprenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inscriptions",
                        to="joatham_apprenants.apprenant",
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inscriptions_formations",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "formation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inscriptions",
                        to="joatham_apprenants.formation",
                    ),
                ),
            ],
            options={"ordering": ["-date_inscription", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="inscriptionformation",
            constraint=models.UniqueConstraint(
                fields=("entreprise", "apprenant", "formation"),
                name="uniq_inscription_formation_par_entreprise",
            ),
        ),
    ]

