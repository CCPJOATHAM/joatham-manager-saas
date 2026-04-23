from django import forms

from .models import Service


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["nom", "prix", "actif"]
        labels = {
            "nom": "Nom du service",
            "prix": "Prix",
            "actif": "Service actif",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nom"].widget.attrs.update({"placeholder": "Nom du service"})
        self.fields["prix"].widget.attrs.update({"placeholder": "0.00", "step": "0.01", "min": "0"})
