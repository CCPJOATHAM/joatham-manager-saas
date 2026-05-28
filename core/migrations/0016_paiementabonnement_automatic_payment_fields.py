import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0015_alter_activitylog_entreprise"),
    ]

    operations = [
        migrations.AddField(
            model_name="paiementabonnement",
            name="amount_expected",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="amount_paid",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="checkout_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="paiements_abonnement_crees",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="external_reference",
            field=models.CharField(blank=True, db_index=True, max_length=80, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="failure_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="last_webhook_event_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=180),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="paid_currency",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="provider",
            field=models.CharField(blank=True, db_index=True, default="manual", max_length=50),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="provider_checkout_id",
            field=models.CharField(blank=True, default="", max_length=180),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="provider_status",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="provider_transaction_id",
            field=models.CharField(blank=True, max_length=180, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="raw_provider_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="paiementabonnement",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="paiementabonnement",
            name="methode_paiement",
            field=models.CharField(
                choices=[
                    ("manuel", "Manuel"),
                    ("automatique", "Automatique"),
                    ("mobile_money", "Mobile Money"),
                    ("carte", "Carte"),
                    ("virement", "Virement"),
                    ("cash", "Cash"),
                ],
                default="manuel",
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="paiementabonnement",
            name="statut",
            field=models.CharField(
                choices=[
                    ("en_attente", "En attente"),
                    ("en_cours", "En cours"),
                    ("approuvee", "Approuvee"),
                    ("valide", "Valide"),
                    ("refuse", "Refuse"),
                    ("annule", "Annule"),
                    ("echoue", "Echoue"),
                    ("expire", "Expire"),
                ],
                default="en_attente",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="paiementabonnement",
            index=models.Index(fields=["provider", "statut", "date_creation"], name="core_paieme_provider_77a7_idx"),
        ),
    ]
