from django import forms
from django.utils.translation import gettext_lazy as _


class CompanyDeletionConfirmationForm(forms.Form):
    confirmation_name = forms.CharField(label=_("Nom exact de l'entreprise"), max_length=100, strip=False,
                                       widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "none", "spellcheck": "false"}))
    reason = forms.CharField(label=_("Motif"), max_length=2000, widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, expected_name=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_name = expected_name

    def clean_confirmation_name(self):
        name = self.cleaned_data["confirmation_name"]
        if self.expected_name is not None and name != self.expected_name:
            raise forms.ValidationError(_("Le nom saisi ne correspond pas exactement au nom de l'entreprise."))
        return name
