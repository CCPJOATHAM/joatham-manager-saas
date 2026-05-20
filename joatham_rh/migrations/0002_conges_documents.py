import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("joatham_rh", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DemandeConge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "type_conge",
                    models.CharField(
                        choices=[
                            ("annuel", "Annuel"),
                            ("maladie", "Maladie"),
                            ("exceptionnel", "Exceptionnel"),
                            ("sans_solde", "Sans solde"),
                            ("autre", "Autre"),
                        ],
                        max_length=20,
                    ),
                ),
                ("date_debut", models.DateField()),
                ("date_fin", models.DateField()),
                ("motif", models.TextField(blank=True, default="")),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("brouillon", "Brouillon"),
                            ("en_attente", "En attente"),
                            ("approuve", "Approuve"),
                            ("refuse", "Refuse"),
                            ("annule", "Annule"),
                        ],
                        default="en_attente",
                        max_length=20,
                    ),
                ),
                ("date_decision", models.DateTimeField(blank=True, null=True)),
                ("commentaire_decision", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approuve_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rh_conges_decides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "employe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conges",
                        to="joatham_rh.employe",
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rh_conges",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={"ordering": ["-date_debut", "-id"]},
        ),
        migrations.CreateModel(
            name="DocumentRH",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "type_document",
                    models.CharField(
                        choices=[
                            ("contrat", "Contrat"),
                            ("piece_identite", "Piece d'identite"),
                            ("attestation", "Attestation"),
                            ("certificat", "Certificat"),
                            ("autre", "Autre"),
                        ],
                        max_length=30,
                    ),
                ),
                ("titre", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("date_document", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents_rh",
                        to="joatham_rh.employe",
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rh_documents",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="demandeconge",
            constraint=models.CheckConstraint(
                condition=models.Q(date_fin__gte=models.F("date_debut")),
                name="rh_conge_date_fin_gte_debut",
            ),
        ),
        migrations.AddIndex(
            model_name="demandeconge",
            index=models.Index(fields=["entreprise", "statut", "date_debut"], name="rh_conge_ent_statut_dt_idx"),
        ),
        migrations.AddIndex(
            model_name="demandeconge",
            index=models.Index(fields=["entreprise", "date_debut"], name="rh_conge_ent_debut_idx"),
        ),
        migrations.AddIndex(
            model_name="demandeconge",
            index=models.Index(fields=["employe", "date_debut"], name="rh_conge_emp_debut_idx"),
        ),
        migrations.AddIndex(
            model_name="documentrh",
            index=models.Index(fields=["entreprise", "type_document"], name="rh_doc_ent_type_idx"),
        ),
        migrations.AddIndex(
            model_name="documentrh",
            index=models.Index(fields=["entreprise", "created_at"], name="rh_doc_ent_created_idx"),
        ),
        migrations.AddIndex(
            model_name="documentrh",
            index=models.Index(fields=["employe", "created_at"], name="rh_doc_emp_created_idx"),
        ),
    ]
