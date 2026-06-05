from django import forms

from .models import EntreprisePrintSettings, Service


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


class EntreprisePrintSettingsForm(forms.ModelForm):
    class Meta:
        model = EntreprisePrintSettings
        fields = [
            "pos_width",
            "default_invoice_format",
            "pos_show_logo",
            "pos_show_company_name",
            "pos_show_address",
            "pos_show_phone",
            "pos_show_email",
            "pos_show_tax_info",
            "pos_show_generated_by",
            "pos_footer_message",
        ]
        labels = {
            "pos_width": "Largeur ticket POS",
            "default_invoice_format": "Format d'impression par defaut",
            "pos_show_logo": "Afficher le logo sur le ticket",
            "pos_show_company_name": "Afficher le nom de l'entreprise",
            "pos_show_address": "Afficher l'adresse",
            "pos_show_phone": "Afficher le telephone",
            "pos_show_email": "Afficher l'email",
            "pos_show_tax_info": "Afficher RCCM, NIF et ID NAT",
            "pos_show_generated_by": "Afficher Genere par JOATHAM Manager",
            "pos_footer_message": "Texte de pied de ticket",
        }
        widgets = {
            "pos_footer_message": forms.Textarea(attrs={"rows": 3, "maxlength": 180}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name.startswith("pos_show_"):
                continue
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["pos_footer_message"].widget.attrs.update(
            {
                "placeholder": "Merci pour votre confiance",
            }
        )
