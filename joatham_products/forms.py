from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Produit


class ProduitForm(forms.ModelForm):
    class Meta:
        model = Produit
        fields = [
            "nom",
            "description",
            "reference",
            "prix_unitaire",
            "quantite_stock",
            "seuil_alerte",
            "actif",
        ]
        labels = {
            "nom": _("Nom du produit"),
            "description": _("Description"),
            "reference": _("Reference"),
            "prix_unitaire": _("Prix unitaire"),
            "quantite_stock": _("Quantite en stock"),
            "seuil_alerte": _("Seuil d'alerte"),
            "actif": _("Produit actif"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nom"].widget.attrs.update({"placeholder": _("Nom du produit")})
        self.fields["description"].widget = forms.Textarea(
            attrs={"rows": 3, "placeholder": _("Description commerciale ou technique")}
        )
        self.fields["reference"].widget.attrs.update({"placeholder": _("Code ou reference")})
        self.fields["prix_unitaire"].widget.attrs.update({"placeholder": "0.00", "step": "0.01", "min": "0"})
        self.fields["quantite_stock"].widget.attrs.update({"placeholder": "0", "min": "0"})
        self.fields["seuil_alerte"].widget.attrs.update({"placeholder": "0", "min": "0"})
