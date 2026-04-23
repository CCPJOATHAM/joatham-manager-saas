from django.contrib import admin

from .models import Produit


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ("nom", "reference", "entreprise", "quantite_stock", "seuil_alerte", "actif")
    list_filter = ("actif", "entreprise")
    search_fields = ("nom", "reference")
