from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import ExchangeRate, PaiementAbonnement, PlatformSettings
from core.services.exchange_rates import get_company_currency, get_plan_price_for_company
from core.services.world import get_country_choices, get_currency_choices
from joatham_users.models import Abonnement, Entreprise


MAINTENANCE_MODULE_CHOICES = [
    ("dashboard", _("Dashboard")),
    ("clients", _("Clients")),
    ("factures", _("Factures")),
    ("services", _("Services")),
    ("depenses", _("Depenses")),
    ("comptabilite", _("Comptabilite")),
    ("apprenants", _("Apprenants")),
    ("abonnements", _("Abonnements")),
    ("utilisateurs", _("Utilisateurs")),
    ("messages", _("Messagerie")),
]

MANUAL_PAYMENT_PERIOD_CHOICES = [
    (30, _("30 jours")),
    (90, _("90 jours")),
    (180, _("180 jours")),
    (365, _("365 jours")),
]


class ExchangeRateManualForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        fields = ["devise_source", "devise_cible", "taux", "date_taux", "actif"]
        labels = {
            "devise_source": _("Devise source"),
            "devise_cible": _("Devise cible"),
            "taux": _("Taux"),
            "date_taux": _("Date du taux"),
            "actif": _("Actif"),
        }
        widgets = {
            "devise_source": forms.TextInput(attrs={"placeholder": "USD"}),
            "devise_cible": forms.TextInput(attrs={"placeholder": "CDF"}),
            "date_taux": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_taux"].required = False

    def clean_devise_source(self):
        return (self.cleaned_data["devise_source"] or "").strip().upper()

    def clean_devise_cible(self):
        return (self.cleaned_data["devise_cible"] or "").strip().upper()

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.source_provider = "manuel"
        if instance.date_taux is None:
            from django.utils import timezone

            instance.date_taux = timezone.now()
        if commit:
            instance.save()
            self.save_m2m()
        return instance


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
        label=_("Plan"),
        empty_label=_("Choisir un plan"),
    )

    class Meta:
        model = PaiementAbonnement
        fields = ["plan", "duree", "telephone_paiement", "reference_paiement", "preuve_paiement"]
        labels = {
            "duree": _("Periode"),
            "telephone_paiement": _("Numero de paiement"),
            "reference_paiement": _("Reference de paiement"),
            "preuve_paiement": _("Preuve de paiement"),
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


class ManualSubscriptionPaymentForm(forms.Form):
    plan = forms.ModelChoiceField(
        queryset=Abonnement.objects.none(),
        label=_("Plan"),
        empty_label=_("Choisir un plan"),
    )
    montant = forms.DecimalField(label=_("Montant recu"), min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    devise = forms.CharField(label=_("Devise"), max_length=10)
    montant_usd = forms.DecimalField(
        label=_("Montant USD"),
        required=False,
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
    )
    taux_change_reference = forms.DecimalField(
        label=_("Taux manuel"),
        required=False,
        min_value=Decimal("0.0001"),
        max_digits=14,
        decimal_places=4,
    )
    methode_paiement = forms.ChoiceField(label=_("Methode de paiement"), choices=PaiementAbonnement.Methode.choices)
    reference_paiement = forms.CharField(label=_("Reference ou note"), required=False, max_length=120)
    periode_jours = forms.TypedChoiceField(
        label=_("Periode payee"),
        choices=MANUAL_PAYMENT_PERIOD_CHOICES,
        coerce=int,
    )
    date_paiement = forms.DateField(
        label=_("Date de paiement"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entreprise = entreprise
        self.fields["plan"].queryset = Abonnement.objects.filter(actif=True).order_by("prix", "nom")
        subscription = getattr(entreprise, "abonnement_entreprise", None) if entreprise is not None else None
        current_plan = getattr(subscription, "plan", None)
        if current_plan is not None:
            price = get_plan_price_for_company(current_plan, entreprise)
            self.fields["plan"].initial = current_plan
            self.fields["montant"].initial = price["estimated_amount"] or price["official_amount"]
            self.fields["devise"].initial = price["company_currency"]
            self.fields["montant_usd"].initial = price["official_amount"]
            self.fields["taux_change_reference"].initial = price["rate"]
        elif entreprise is not None:
            self.fields["devise"].initial = get_company_currency(entreprise)


class PlatformSettingsForm(forms.ModelForm):
    nom_plateforme = forms.CharField(required=False)
    email_systeme = forms.EmailField(required=False)
    devise_defaut = forms.CharField(required=False)
    devise_plateforme = forms.CharField(required=False)
    exchange_rate_provider = forms.CharField(required=False)
    exchange_rate_api_key = forms.CharField(required=False)
    exchange_rate_cache_hours = forms.IntegerField(required=False, min_value=1)
    allow_manual_exchange_rate_fallback = forms.BooleanField(required=False)
    duree_essai_jours = forms.IntegerField(required=False, min_value=1)
    message_maintenance = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    maintenance_allowed_ips = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    maintenance_modules = forms.MultipleChoiceField(
        choices=MAINTENANCE_MODULE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = PlatformSettings
        fields = [
            "nom_plateforme",
            "email_systeme",
            "devise_defaut",
            "devise_plateforme",
            "exchange_rate_provider",
            "exchange_rate_api_key",
            "exchange_rate_cache_hours",
            "allow_manual_exchange_rate_fallback",
            "duree_essai_jours",
            "mode_maintenance",
            "message_maintenance",
            "maintenance_allowed_ips",
            "maintenance_modules",
        ]
        labels = {
            "nom_plateforme": "Nom plateforme",
            "email_systeme": "Email systeme",
            "devise_defaut": "Devise par defaut",
            "devise_plateforme": "Devise plateforme",
            "exchange_rate_provider": "Provider taux de change",
            "exchange_rate_api_key": "Cle API taux de change",
            "exchange_rate_cache_hours": "Cache taux en heures",
            "allow_manual_exchange_rate_fallback": "Autoriser fallback manuel",
            "duree_essai_jours": "Duree essai gratuit",
            "mode_maintenance": "Mode maintenance",
            "message_maintenance": "Message maintenance",
            "maintenance_allowed_ips": "IPs autorisees",
            "maintenance_modules": "Modules en maintenance",
        }
        widgets = {
            "nom_plateforme": forms.TextInput(attrs={"placeholder": "JOATHAM Manager"}),
            "email_systeme": forms.EmailInput(attrs={"placeholder": "admin@joatham.com"}),
            "devise_defaut": forms.Select(choices=[]),
            "devise_plateforme": forms.TextInput(attrs={"placeholder": "USD"}),
            "exchange_rate_provider": forms.TextInput(attrs={"placeholder": "exchangerate_api"}),
            "exchange_rate_api_key": forms.PasswordInput(render_value=True),
            "exchange_rate_cache_hours": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "duree_essai_jours": forms.NumberInput(attrs={"min": "1", "step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currency_choices = list(get_currency_choices())
        current_currency = (getattr(self.instance, "devise_defaut", "") or "").strip().upper()
        if current_currency and current_currency not in {value for value, _ in currency_choices}:
            currency_choices.insert(0, (current_currency, current_currency))
        self.fields["devise_defaut"].choices = currency_choices

    def clean(self):
        cleaned_data = super().clean()
        for field_name in (
            "nom_plateforme",
            "email_systeme",
            "devise_defaut",
            "devise_plateforme",
            "exchange_rate_provider",
            "exchange_rate_api_key",
            "exchange_rate_cache_hours",
            "duree_essai_jours",
            "message_maintenance",
            "maintenance_allowed_ips",
        ):
            value = cleaned_data.get(field_name)
            if value in ("", None):
                cleaned_data[field_name] = getattr(self.instance, field_name)
        return cleaned_data
