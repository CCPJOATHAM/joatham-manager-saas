from django import forms
from django.utils.translation import gettext_lazy as _

from joatham_caisse.models import Caisse

from .models import Depense


class DepenseForm(forms.ModelForm):
    caisse = forms.ModelChoiceField(
        queryset=Caisse.objects.none(),
        required=False,
        empty_label=_("Aucune caisse"),
        label=_("Payer depuis une caisse"),
    )

    def __init__(self, *args, **kwargs):
        entreprise = kwargs.pop("entreprise", None)
        super().__init__(*args, **kwargs)
        self.fields["description"].widget.attrs.update(
            {
                "placeholder": _("Description de la depense"),
            }
        )
        self.fields["montant"].widget.attrs.update(
            {
                "placeholder": _("Montant"),
                "step": "0.01",
                "min": "0",
            }
        )
        self.fields["caisse"].widget.attrs.update(
            {
                "placeholder": _("Selectionnez une caisse"),
            }
        )
        if entreprise is not None:
            self.fields["caisse"].queryset = Caisse.objects.filter(entreprise=entreprise, est_active=True).order_by("nom", "id")

    class Meta:
        model = Depense
        fields = ["description", "montant", "caisse"]
