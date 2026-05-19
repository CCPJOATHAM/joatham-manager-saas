from decimal import Decimal

from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from .models import Produit, StockMovement


class BaseProduitForm(forms.ModelForm):
    class Meta:
        model = Produit
        fields = [
            "nom",
            "description",
            "reference",
            "prix_unitaire",
            "seuil_alerte",
            "actif",
        ]
        labels = {
            "nom": _("Nom du produit"),
            "description": _("Description"),
            "reference": _("Reference"),
            "prix_unitaire": _("Prix unitaire"),
            "seuil_alerte": _("Seuil d'alerte"),
            "actif": _("Produit actif"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prix_unitaire"].min_value = Decimal("0")
        self.fields["seuil_alerte"].min_value = 0
        self.fields["nom"].widget.attrs.update({"placeholder": _("Nom du produit")})
        self.fields["description"].widget = forms.Textarea(
            attrs={"rows": 3, "placeholder": _("Description commerciale ou technique")}
        )
        self.fields["reference"].widget.attrs.update({"placeholder": _("Code ou reference")})
        self.fields["prix_unitaire"].widget.attrs.update({"placeholder": "0.00", "step": "0.01", "min": "0"})
        self.fields["seuil_alerte"].widget.attrs.update({"placeholder": "0", "min": "0"})


class ProduitCreateForm(BaseProduitForm):
    quantite_stock = forms.IntegerField(min_value=0, label=_("Stock initial"))

    class Meta(BaseProduitForm.Meta):
        fields = BaseProduitForm.Meta.fields[:]
        fields.insert(4, "quantite_stock")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantite_stock"].widget.attrs.update({"placeholder": "0", "min": "0"})


class ProduitUpdateForm(BaseProduitForm):
    pass


class StockMovementForm(forms.Form):
    produit = forms.ModelChoiceField(queryset=Produit.objects.none(), label=_("Produit"))
    movement_type = forms.ChoiceField(label=_("Type de mouvement"))
    quantity = forms.IntegerField(min_value=1, label=_("Quantite"))
    reference = forms.CharField(max_length=120, required=False, label=_("Reference"))
    reason = forms.CharField(max_length=120, required=False, label=_("Motif"))
    comment = forms.CharField(required=False, label=_("Commentaire"), widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, entreprise=None, allowed_types=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_types = allowed_types or []
        self.fields["produit"].queryset = Produit.objects.filter(entreprise=entreprise).order_by("nom", "id")
        self.fields["movement_type"].choices = [
            (code, label)
            for code, label in StockMovement.MovementType.choices
            if code in allowed_types
        ]
        self.fields["produit"].widget.attrs.update({"data-stock-form": "product"})
        self.fields["quantity"].widget.attrs.update({"placeholder": "0", "min": "1"})
        self.fields["reference"].widget.attrs.update({"placeholder": _("Bon, document ou reference interne")})
        self.fields["reason"].widget.attrs.update({"placeholder": _("Expliquez brievement l'operation")})
        self.fields["comment"].widget.attrs.update({"placeholder": _("Commentaire complementaire")})

    def clean_movement_type(self):
        movement_type = self.cleaned_data["movement_type"]
        allowed_values = {choice[0] for choice in self.fields["movement_type"].choices}
        if movement_type not in allowed_values:
            raise forms.ValidationError(_("Le type de mouvement selectionne est invalide."))
        return movement_type


class InventorySessionForm(forms.Form):
    name = forms.CharField(max_length=150, label=_("Nom de l'inventaire"))
    comment = forms.CharField(
        required=False,
        label=_("Commentaire"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.update({"placeholder": _("Exemple : Inventaire mensuel magasin principal")})
        self.fields["comment"].widget.attrs.update({"placeholder": _("Notes ou consignes pour cette session d'inventaire")})


class InventoryCountForm(forms.Form):
    line_id = forms.IntegerField(widget=forms.HiddenInput)
    counted_quantity = forms.IntegerField(min_value=0, label=_("Quantite comptee"))
    comment = forms.CharField(
        required=False,
        label=_("Commentaire"),
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean_line_id(self):
        line_id = self.cleaned_data["line_id"]
        if line_id <= 0:
            raise forms.ValidationError(_("La ligne d'inventaire est invalide."))
        return line_id


InventoryCountFormSet = formset_factory(InventoryCountForm, extra=0)
