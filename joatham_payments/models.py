from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class PaymentTransaction(models.Model):
    class TransactionType(models.TextChoices):
        ENCAISSEMENT = "encaissement", "Encaissement"
        DECAISSEMENT = "decaissement", "Decaissement"
        REMBOURSEMENT = "remboursement", "Remboursement"
        AJUSTEMENT = "ajustement", "Ajustement"

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MPESA = "mpesa", "M-Pesa"
        ORANGE_MONEY = "orange_money", "Orange Money"
        AIRTEL_MONEY = "airtel_money", "Airtel Money"
        AFRIMONEY = "afrimoney", "Afrimoney"
        BANK_TRANSFER = "bank_transfer", "Virement bancaire"
        CARD = "card", "Carte bancaire"
        OTHER = "other", "Autre"

    class MobileOperator(models.TextChoices):
        MPESA = "mpesa", "M-Pesa"
        ORANGE_MONEY = "orange_money", "Orange Money"
        AIRTEL_MONEY = "airtel_money", "Airtel Money"
        AFRIMONEY = "afrimoney", "Afrimoney"
        OTHER = "other", "Autre"

    class Status(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        CONFIRME = "confirme", "Confirme"
        REJETE = "rejete", "Rejete"
        ANNULE = "annule", "Annule"

    MOBILE_MONEY_METHODS = {
        Method.MPESA,
        Method.ORANGE_MONEY,
        Method.AIRTEL_MONEY,
        Method.AFRIMONEY,
    }

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="payment_transactions",
    )
    transaction_type = models.CharField(
        max_length=30,
        choices=TransactionType.choices,
        default=TransactionType.ENCAISSEMENT,
    )
    method = models.CharField(max_length=30, choices=Method.choices, default=Method.CASH)
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=10, default="CDF")
    reference = models.CharField(max_length=120, blank=True, default="")
    phone_number = models.CharField(max_length=50, blank=True, default="")
    mobile_operator = models.CharField(
        max_length=30,
        choices=MobileOperator.choices,
        blank=True,
        default="",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.EN_ATTENTE)
    transaction_date = models.DateTimeField(default=timezone.now)
    validation_date = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="payment_transactions_validated",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="payment_transactions_created",
        null=True,
        blank=True,
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="payment_transactions_cancelled",
        null=True,
        blank=True,
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    attachment = models.FileField(upload_to="payments/supporting_docs/", null=True, blank=True)
    facture = models.ForeignKey(
        "joatham_billing.Facture",
        on_delete=models.SET_NULL,
        related_name="payment_transactions",
        null=True,
        blank=True,
    )
    paiement_facture = models.OneToOneField(
        "joatham_billing.PaiementFacture",
        on_delete=models.SET_NULL,
        related_name="payment_transaction",
        null=True,
        blank=True,
    )
    depense = models.ForeignKey(
        "joatham_depenses.Depense",
        on_delete=models.SET_NULL,
        related_name="payment_transactions",
        null=True,
        blank=True,
    )
    caisse = models.ForeignKey(
        "joatham_caisse.Caisse",
        on_delete=models.SET_NULL,
        related_name="payment_transactions",
        null=True,
        blank=True,
    )
    session_caisse = models.ForeignKey(
        "joatham_caisse.SessionCaisse",
        on_delete=models.SET_NULL,
        related_name="payment_transactions",
        null=True,
        blank=True,
    )
    mouvement_caisse = models.OneToOneField(
        "joatham_caisse.MouvementCaisse",
        on_delete=models.SET_NULL,
        related_name="payment_transaction",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-transaction_date", "-id"]
        indexes = [
            models.Index(fields=["entreprise", "status", "transaction_date"], name="pay_tx_ent_status_dt_idx"),
            models.Index(fields=["entreprise", "method", "transaction_date"], name="pay_tx_ent_method_dt_idx"),
            models.Index(fields=["entreprise", "transaction_type"], name="pay_tx_ent_type_idx"),
            models.Index(fields=["facture"], name="pay_tx_facture_idx"),
            models.Index(fields=["caisse", "session_caisse"], name="pay_tx_cash_session_idx"),
            models.Index(fields=["reference"], name="pay_tx_reference_idx"),
        ]

    def __str__(self):
        return f"{self.get_method_display()} - {self.amount} {self.currency}"

    @property
    def is_mobile_money(self):
        return self.method in self.MOBILE_MONEY_METHODS

    @property
    def is_confirmed(self):
        return self.status == self.Status.CONFIRME

    def save(self, *args, **kwargs):
        if not self.currency and self.entreprise_id:
            self.currency = getattr(self.entreprise, "devise", "") or "CDF"
        self.reference = (self.reference or "").strip()
        self.phone_number = (self.phone_number or "").strip()
        self.mobile_operator = (self.mobile_operator or "").strip()
        self.note = (self.note or "").strip()
        super().save(*args, **kwargs)

