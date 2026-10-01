import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0017_paiementabonnement_provider_notify_token"),
        ("joatham_users", "0020_useractivesession"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntentionAbonnement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "duree",
                    models.CharField(
                        choices=[
                            ("mensuel", "Mensuel"),
                            ("trimestriel", "Trimestriel"),
                            ("semestriel", "Semestriel"),
                            ("annuel", "Annuel"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("en_attente", "En attente"),
                            ("paiement_initie", "Paiement initie"),
                            ("consommee", "Consommee"),
                            ("annulee", "Annulee"),
                            ("expiree", "Expiree"),
                        ],
                        db_index=True,
                        default="en_attente",
                        max_length=30,
                    ),
                ),
                ("source", models.CharField(blank=True, default="landing", max_length=50)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                ("date_expiration", models.DateTimeField(blank=True, null=True)),
                ("date_consommation", models.DateTimeField(blank=True, null=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="intentions_abonnement",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "paiement",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="intentions_abonnement",
                        to="core.paiementabonnement",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="intentions_abonnement",
                        to="joatham_users.abonnement",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="intentions_abonnement",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-date_creation", "-id"],
                "indexes": [
                    models.Index(fields=["entreprise", "statut", "date_creation"], name="core_intent_entrepr_34895e_idx"),
                    models.Index(fields=["utilisateur", "statut", "date_creation"], name="core_intent_utilisa_e9ce95_idx"),
                    models.Index(fields=["paiement", "statut"], name="core_intent_paiemen_f1689d_idx"),
                ],
            },
        ),
    ]
