from django import forms

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
            "nom": "Nom du produit",
            "description": "Description",
            "reference": "Reference",
            "prix_unitaire": "Prix unitaire",
            "quantite_stock": "Quantite en stock",
            "seuil_alerte": "Seuil d'alerte",
            "actif": "Produit actif",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nom"].widget.attrs.update({"placeholder": "Nom du produit"})
        self.fields["description"].widget = forms.Textarea(
            attrs={"rows": 3, "placeholder": "Description commerciale ou technique"}
        )
        self.fields["reference"].widget.attrs.update({"placeholder": "Code ou reference"})
        self.fields["prix_unitaire"].widget.attrs.update({"placeholder": "0.00", "step": "0.01", "min": "0"})
        self.fields["quantite_stock"].widget.attrs.update({"placeholder": "0", "min": "0"})
        self.fields["seuil_alerte"].widget.attrs.update({"placeholder": "0", "min": "0"})
