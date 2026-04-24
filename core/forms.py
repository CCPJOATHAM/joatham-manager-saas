from django import forms

from core.models import PaiementAbonnement
from core.services.world import get_country_choices, get_currency_choices
from joatham_users.models import Abonnement, Entreprise


class EntrepriseSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        country_choices = list(get_country_choices())
        currency_choices = list(get_currency_choices())
        current_country = (getattr(self.instance, "pays", "") or "").strip()
        current_currency = (getattr(self.instance, "devise", "") or "").strip().upper()

        if current_country and current_country not in {value for value, _ in country_choices}:
            country_choices.insert(0, (current_country, current_country))
        if current_currency and current_currency not in {value for value, _ in currency_choices}:
            currency_choices.insert(0, (current_currency, current_currency))

        self.fields["pays"].choices = country_choices
        self.fields["devise"].choices = currency_choices
        self.fields["taux_tva_defaut"].widget.attrs.update(
            {
                "placeholder": "0.00",
                "step": "0.01",
                "min": "0",
            }
        )

    class Meta:
        model = Entreprise
        fields = [
            "nom",
            "raison_sociale",
            "adresse",
            "ville",
            "pays",
            "devise",
            "taux_tva_defaut",
            "referentiel_comptable",
            "telephone",
            "email",
            "banque",
            "compte_bancaire",
            "rccm",
            "id_nat",
            "numero_impot",
            "logo",
        ]

        widgets = {
            "adresse": forms.TextInput(attrs={"placeholder": "Adresse de l'entreprise"}),
            "ville": forms.TextInput(attrs={"placeholder": "Ville"}),
            "pays": forms.TextInput(attrs={"placeholder": "Pays"}),
            "telephone": forms.TextInput(attrs={"placeholder": "+243..."}),
            "email": forms.EmailInput(attrs={"placeholder": "contact@entreprise.com"}),
            "banque": forms.TextInput(attrs={"placeholder": "Banque"}),
            "compte_bancaire": forms.TextInput(attrs={"placeholder": "Numéro de compte"}),
            "rccm": forms.TextInput(attrs={"placeholder": "RCCM"}),
            "id_nat": forms.TextInput(attrs={"placeholder": "ID NAT"}),
            "numero_impot": forms.TextInput(attrs={"placeholder": "Numéro d'impôt"}),
        }


class PaiementAbonnementForm(forms.ModelForm):
    plan = forms.ModelChoiceField(
        queryset=Abonnement.objects.none(),
        label="Plan",
        empty_label="Choisir un plan",
    )

    class Meta:
        model = PaiementAbonnement
        fields = ["plan", "duree", "telephone_paiement", "reference_paiement", "preuve_paiement"]
        labels = {
            "duree": "Période",
            "telephone_paiement": "Numéro de paiement",
            "reference_paiement": "Référence de paiement",
            "preuve_paiement": "Preuve de paiement",
        }
        widgets = {
            "telephone_paiement": forms.TextInput(
                attrs={"placeholder": "Ex. +243... pour le compte utilisé"}
            ),
            "reference_paiement": forms.TextInput(
                attrs={"placeholder": "Ex. transaction Mobile Money, virement, reçu"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = Abonnement.objects.filter(actif=True, prix__gt=0).order_by("prix", "nom")
        self.fields["telephone_paiement"].required = False
        self.fields["preuve_paiement"].required = False
