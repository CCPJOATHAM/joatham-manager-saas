import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("joatham_users", "0020_useractivesession"),
        ("joatham_billing", "0009_alter_paiementfacture_mode"),
        ("joatham_depenses", "0003_depense_caisse_session_caisse"),
        ("joatham_caisse", "0003_mouvementcaisse_moyen_paiement"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "transaction_type",
                    models.CharField(
                        choices=[
                            ("encaissement", "Encaissement"),
                            ("decaissement", "Decaissement"),
                            ("remboursement", "Remboursement"),
                            ("ajustement", "Ajustement"),
                        ],
                        default="encaissement",
                        max_length=30,
                    ),
                ),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("cash", "Cash"),
                            ("mpesa", "M-Pesa"),
                            ("orange_money", "Orange Money"),
                            ("airtel_money", "Airtel Money"),
                            ("afrimoney", "Afrimoney"),
                            ("bank_transfer", "Virement bancaire"),
                            ("card", "Carte bancaire"),
                            ("other", "Autre"),
                        ],
                        default="cash",
                        max_length=30,
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("currency", models.CharField(default="CDF", max_length=10)),
                ("reference", models.CharField(blank=True, default="", max_length=120)),
                ("phone_number", models.CharField(blank=True, default="", max_length=50)),
                (
                    "mobile_operator",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("mpesa", "M-Pesa"),
                            ("orange_money", "Orange Money"),
                            ("airtel_money", "Airtel Money"),
                            ("afrimoney", "Afrimoney"),
                            ("other", "Autre"),
                        ],
                        default="",
                        max_length=30,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("en_attente", "En attente"),
                            ("confirme", "Confirme"),
                            ("rejete", "Rejete"),
                            ("annule", "Annule"),
                        ],
                        default="en_attente",
                        max_length=20,
                    ),
                ),
                ("transaction_date", models.DateTimeField(default=django.utils.timezone.now)),
                ("validation_date", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True, default="")),
                ("attachment", models.FileField(blank=True, null=True, upload_to="payments/supporting_docs/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "caisse",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions",
                        to="joatham_caisse.caisse",
                    ),
                ),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions_cancelled",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "depense",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions",
                        to="joatham_depenses.depense",
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_transactions",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "facture",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions",
                        to="joatham_billing.facture",
                    ),
                ),
                (
                    "mouvement_caisse",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transaction",
                        to="joatham_caisse.mouvementcaisse",
                    ),
                ),
                (
                    "paiement_facture",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transaction",
                        to="joatham_billing.paiementfacture",
                    ),
                ),
                (
                    "session_caisse",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions",
                        to="joatham_caisse.sessioncaisse",
                    ),
                ),
                (
                    "validated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions_validated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-transaction_date", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="paymenttransaction",
            index=models.Index(fields=["entreprise", "status", "transaction_date"], name="pay_tx_ent_status_dt_idx"),
        ),
        migrations.AddIndex(
            model_name="paymenttransaction",
            index=models.Index(fields=["entreprise", "method", "transaction_date"], name="pay_tx_ent_method_dt_idx"),
        ),
        migrations.AddIndex(
            model_name="paymenttransaction",
            index=models.Index(fields=["entreprise", "transaction_type"], name="pay_tx_ent_type_idx"),
        ),
        migrations.AddIndex(
            model_name="paymenttransaction",
            index=models.Index(fields=["facture"], name="pay_tx_facture_idx"),
        ),
        migrations.AddIndex(
            model_name="paymenttransaction",
            index=models.Index(fields=["caisse", "session_caisse"], name="pay_tx_cash_session_idx"),
        ),
        migrations.AddIndex(
            model_name="paymenttransaction",
            index=models.Index(fields=["reference"], name="pay_tx_reference_idx"),
        ),
    ]

