from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class Produit(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="produits",
    )
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    reference = models.CharField(max_length=80, blank=True, default="")
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantite_stock = models.PositiveIntegerField(default=0)
    seuil_alerte = models.PositiveIntegerField(default=0)
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["entreprise", "reference"],
                name="unique_product_reference_per_entreprise",
            ),
        ]

    def __str__(self):
        return self.nom

    @property
    def is_rupture(self):
        return self.quantite_stock <= 0

    @property
    def is_stock_faible(self):
        return self.quantite_stock <= self.seuil_alerte

    @property
    def stock_status(self):
        if self.is_rupture:
            return "rupture"
        if self.is_stock_faible:
            return "stock_faible"
        return "en_stock"


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        MANUAL_ENTRY = "manual_entry", "Entree manuelle"
        MANUAL_EXIT = "manual_exit", "Sortie manuelle"
        INVOICE_SALE = "invoice_sale", "Vente facture"
        INVOICE_RESTORE = "invoice_restore", "Restauration facture"
        ADJUSTMENT_POSITIVE = "adjustment_positive", "Ajustement positif"
        ADJUSTMENT_NEGATIVE = "adjustment_negative", "Ajustement negatif"
        INVENTORY_RECOUNT = "inventory_recount", "Inventaire"
        TRANSFER_OUT = "transfer_out", "Transfert sortant"
        TRANSFER_IN = "transfer_in", "Transfert entrant"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="stock_movements",
    )
    produit = models.ForeignKey(
        Produit,
        on_delete=models.CASCADE,
        related_name="stock_movements",
    )
    movement_type = models.CharField(max_length=30, choices=MovementType.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    stock_before = models.PositiveIntegerField(default=0)
    stock_after = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reference = models.CharField(max_length=120, blank=True, default="")
    reason = models.CharField(max_length=120, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    source_app = models.CharField(max_length=50, blank=True, default="")
    source_model = models.CharField(max_length=100, blank=True, default="")
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="stock_mov_qty_gt_zero"),
            models.CheckConstraint(condition=Q(stock_before__gte=0), name="stock_mov_before_gte_zero"),
            models.CheckConstraint(condition=Q(stock_after__gte=0), name="stock_mov_after_gte_zero"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "created_at"], name="stock_mov_ent_created_idx"),
            models.Index(fields=["entreprise", "movement_type", "created_at"], name="stock_mov_ent_type_dt_idx"),
            models.Index(fields=["produit", "created_at"], name="stock_mov_prod_date_idx"),
            models.Index(fields=["source_app", "source_model", "source_id"], name="stock_mov_source_idx"),
            models.Index(fields=["entreprise", "produit", "created_at"], name="stock_mov_ent_prod_dt_idx"),
        ]

    def save(self, *args, **kwargs):
        self.reference = (self.reference or "").strip()
        self.reason = (self.reason or "").strip()
        self.comment = (self.comment or "").strip()
        self.source_app = (self.source_app or "").strip()
        self.source_model = (self.source_model or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.produit} - {self.movement_type} - {self.quantity}"
