from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("joatham_users", "0020_useractivesession"),
    ]

    operations = [
        migrations.CreateModel(
            name="Caisse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=120)),
                ("code", models.CharField(max_length=40)),
                ("description", models.TextField(blank=True, null=True)),
                ("devise", models.CharField(default="CDF", max_length=10)),
                ("est_active", models.BooleanField(default=True)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                (
                    "cree_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="caisses_creees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="caisses",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={"ordering": ["nom", "id"]},
        ),
        migrations.CreateModel(
            name="SessionCaisse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date_ouverture", models.DateTimeField(default=django.utils.timezone.now)),
                ("date_fermeture", models.DateTimeField(blank=True, null=True)),
                (
                    "solde_initial",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                ("solde_theorique", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("solde_reel", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("ecart", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("ouverte", "Ouverte"),
                            ("fermee", "Fermee"),
                            ("validee", "Validee"),
                            ("annulee", "Annulee"),
                        ],
                        default="ouverte",
                        max_length=20,
                    ),
                ),
                ("commentaire_ouverture", models.TextField(blank=True, default="")),
                ("commentaire_fermeture", models.TextField(blank=True, default="")),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                (
                    "caisse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sessions",
                        to="joatham_caisse.caisse",
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sessions_caisse",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "utilisateur_fermeture",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sessions_caisse_fermees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "utilisateur_ouverture",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sessions_caisse_ouvertes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-date_ouverture", "-id"]},
        ),
        migrations.CreateModel(
            name="MouvementCaisse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "type_mouvement",
                    models.CharField(
                        choices=[
                            ("entree", "Entree"),
                            ("sortie", "Sortie"),
                            ("depense", "Depense"),
                            ("paiement_facture", "Paiement facture"),
                            ("ajustement", "Ajustement"),
                            ("transfert", "Transfert"),
                        ],
                        max_length=30,
                    ),
                ),
                (
                    "montant",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("devise", models.CharField(default="CDF", max_length=10)),
                ("libelle", models.CharField(max_length=255)),
                ("reference", models.CharField(blank=True, default="", max_length=100)),
                ("source_app", models.CharField(blank=True, default="", max_length=50)),
                ("source_model", models.CharField(blank=True, default="", max_length=100)),
                ("source_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("date_mouvement", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "statut",
                    models.CharField(
                        choices=[("brouillon", "Brouillon"), ("confirme", "Confirme"), ("annule", "Annule")],
                        default="confirme",
                        max_length=20,
                    ),
                ),
                ("commentaire", models.TextField(blank=True, default="")),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                (
                    "caisse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mouvements",
                        to="joatham_caisse.caisse",
                    ),
                ),
                (
                    "cree_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mouvements_caisse_crees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mouvements_caisse",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mouvements",
                        to="joatham_caisse.sessioncaisse",
                    ),
                ),
            ],
            options={"ordering": ["-date_mouvement", "-id"]},
        ),
        migrations.CreateModel(
            name="ValidationCaisse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date_validation", models.DateTimeField(default=django.utils.timezone.now)),
                ("decision", models.CharField(choices=[("validee", "Validee"), ("rejetee", "Rejetee")], max_length=20)),
                ("commentaire", models.TextField(blank=True, default="")),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="validations_caisse",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="validations",
                        to="joatham_caisse.sessioncaisse",
                    ),
                ),
                (
                    "validee_par",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="validations_caisse_effectuees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-date_validation", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="caisse",
            constraint=models.UniqueConstraint(fields=("entreprise", "code"), name="uniq_caisse_code_by_company"),
        ),
        migrations.AddIndex(
            model_name="caisse",
            index=models.Index(fields=["entreprise", "est_active"], name="cash_company_active_idx"),
        ),
        migrations.AddIndex(
            model_name="caisse",
            index=models.Index(fields=["entreprise", "code"], name="cash_company_code_idx"),
        ),
        migrations.AddConstraint(
            model_name="sessioncaisse",
            constraint=models.UniqueConstraint(
                condition=models.Q(statut="ouverte"),
                fields=("caisse",),
                name="uniq_open_cash_session_per_cashbox",
            ),
        ),
        migrations.AddConstraint(
            model_name="sessioncaisse",
            constraint=models.CheckConstraint(
                condition=models.Q(solde_initial__gte=0),
                name="cash_session_initial_balance_gte_zero",
            ),
        ),
        migrations.AddConstraint(
            model_name="sessioncaisse",
            constraint=models.CheckConstraint(
                condition=models.Q(date_fermeture__isnull=True) | models.Q(date_fermeture__gte=models.F("date_ouverture")),
                name="cash_session_close_after_open",
            ),
        ),
        migrations.AddIndex(
            model_name="sessioncaisse",
            index=models.Index(fields=["entreprise", "statut"], name="cash_session_company_status_idx"),
        ),
        migrations.AddIndex(
            model_name="sessioncaisse",
            index=models.Index(fields=["caisse", "statut"], name="cash_session_cashbox_status_idx"),
        ),
        migrations.AddIndex(
            model_name="sessioncaisse",
            index=models.Index(fields=["entreprise", "date_ouverture"], name="cash_session_company_open_idx"),
        ),
        migrations.AddIndex(
            model_name="sessioncaisse",
            index=models.Index(fields=["entreprise", "date_fermeture"], name="cash_session_company_close_idx"),
        ),
        migrations.AddConstraint(
            model_name="mouvementcaisse",
            constraint=models.CheckConstraint(
                condition=models.Q(montant__gt=0),
                name="cash_movement_amount_gt_zero",
            ),
        ),
        migrations.AddIndex(
            model_name="mouvementcaisse",
            index=models.Index(fields=["entreprise", "date_mouvement"], name="cash_move_company_date_idx"),
        ),
        migrations.AddIndex(
            model_name="mouvementcaisse",
            index=models.Index(fields=["session", "date_mouvement"], name="cash_move_session_date_idx"),
        ),
        migrations.AddIndex(
            model_name="mouvementcaisse",
            index=models.Index(fields=["caisse", "date_mouvement"], name="cash_move_cashbox_date_idx"),
        ),
        migrations.AddIndex(
            model_name="mouvementcaisse",
            index=models.Index(
                fields=["entreprise", "type_mouvement", "date_mouvement"],
                name="cash_move_company_type_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="mouvementcaisse",
            index=models.Index(fields=["source_app", "source_model", "source_id"], name="cash_move_source_idx"),
        ),
        migrations.AddConstraint(
            model_name="validationcaisse",
            constraint=models.UniqueConstraint(fields=("session",), name="uniq_cash_validation_per_session"),
        ),
        migrations.AddIndex(
            model_name="validationcaisse",
            index=models.Index(fields=["entreprise", "date_validation"], name="cash_validation_company_date_idx"),
        ),
        migrations.AddIndex(
            model_name="validationcaisse",
            index=models.Index(fields=["session", "decision"], name="cash_validation_session_decision_idx"),
        ),
    ]
