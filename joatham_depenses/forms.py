from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Depense

class DepenseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
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

    class Meta:
        model = Depense
        fields = ['description', 'montant']
