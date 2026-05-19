import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("joatham_users", "0020_useractivesession"),
    ]

    operations = [
        migrations.CreateModel(
            name="Poste",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True, default="")),
                ("actif", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rh_postes",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={"ordering": ["nom", "id"]},
        ),
        migrations.CreateModel(
            name="Employe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("matricule", models.CharField(max_length=50)),
                ("nom", models.CharField(max_length=120)),
                ("prenom", models.CharField(max_length=120)),
                (
                    "sexe",
                    models.CharField(
                        blank=True,
                        choices=[("homme", "Homme"), ("femme", "Femme"), ("autre", "Autre")],
                        default="",
                        max_length=20,
                    ),
                ),
                ("telephone", models.CharField(blank=True, default="", max_length=50)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("adresse", models.CharField(blank=True, default="", max_length=255)),
                (
                    "type_contrat",
                    models.CharField(
                        choices=[
                            ("cdi", "CDI"),
                            ("cdd", "CDD"),
                            ("stage", "Stage"),
                            ("journalier", "Journalier"),
                            ("prestation", "Prestation"),
                            ("autre", "Autre"),
                        ],
                        default="cdi",
                        max_length=20,
                    ),
                ),
                ("date_embauche", models.DateField()),
                (
                    "salaire_base",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=12,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[("actif", "Actif"), ("suspendu", "Suspendu"), ("sorti", "Sorti")],
                        default="actif",
                        max_length=20,
                    ),
                ),
                ("actif", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rh_employes",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "poste",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="employes",
                        to="joatham_rh.poste",
                    ),
                ),
            ],
            options={"ordering": ["nom", "prenom", "id"]},
        ),
        migrations.CreateModel(
            name="Presence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                (
                    "statut",
                    models.CharField(
                        choices=[("present", "Present"), ("absent", "Absent"), ("retard", "Retard"), ("conge", "Conge")],
                        max_length=20,
                    ),
                ),
                ("heure_arrivee", models.TimeField(blank=True, null=True)),
                ("heure_depart", models.TimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="presences",
                        to="joatham_rh.employe",
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rh_presences",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={"ordering": ["-date", "employe__nom", "id"]},
        ),
        migrations.AddConstraint(
            model_name="poste",
            constraint=models.UniqueConstraint(fields=("entreprise", "nom"), name="rh_unique_poste_nom_per_entreprise"),
        ),
        migrations.AddIndex(
            model_name="poste",
            index=models.Index(fields=["entreprise", "actif"], name="rh_poste_ent_actif_idx"),
        ),
        migrations.AddIndex(
            model_name="poste",
            index=models.Index(fields=["entreprise", "nom"], name="rh_poste_ent_nom_idx"),
        ),
        migrations.AddConstraint(
            model_name="employe",
            constraint=models.UniqueConstraint(fields=("entreprise", "matricule"), name="rh_unique_matricule_per_entreprise"),
        ),
        migrations.AddConstraint(
            model_name="employe",
            constraint=models.CheckConstraint(
                condition=models.Q(salaire_base__isnull=True) | models.Q(salaire_base__gte=0),
                name="rh_employe_salaire_base_gte_zero",
            ),
        ),
        migrations.AddIndex(
            model_name="employe",
            index=models.Index(fields=["entreprise", "statut"], name="rh_emp_ent_statut_idx"),
        ),
        migrations.AddIndex(
            model_name="employe",
            index=models.Index(fields=["entreprise", "actif"], name="rh_emp_ent_actif_idx"),
        ),
        migrations.AddIndex(
            model_name="employe",
            index=models.Index(fields=["entreprise", "matricule"], name="rh_emp_ent_matricule_idx"),
        ),
        migrations.AddConstraint(
            model_name="presence",
            constraint=models.UniqueConstraint(fields=("employe", "date"), name="rh_unique_presence_employe_date"),
        ),
        migrations.AddIndex(
            model_name="presence",
            index=models.Index(fields=["entreprise", "date"], name="rh_presence_ent_date_idx"),
        ),
        migrations.AddIndex(
            model_name="presence",
            index=models.Index(fields=["entreprise", "statut", "date"], name="rh_presence_ent_statut_dt_idx"),
        ),
        migrations.AddIndex(
            model_name="presence",
            index=models.Index(fields=["employe", "date"], name="rh_presence_emp_date_idx"),
        ),
    ]
