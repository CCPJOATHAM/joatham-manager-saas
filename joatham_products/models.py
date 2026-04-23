from django.db import models


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
