from django import forms
from django.utils import timezone

from joatham_billing.models import Facture
from joatham_caisse.models import Caisse, SessionCaisse
from joatham_depenses.models import Depense
from joatham_users.permissions import user_has_permission

from .models import PaymentTransaction


class PaymentTransactionForm(forms.ModelForm):
    confirm_now = forms.BooleanField(
        required=False,
        label="Confirmer immediatement",
        help_text="Disponible uniquement aux utilisateurs habilites a valider les paiements.",
    )

    class Meta:
        model = PaymentTransaction
        fields = [
            "transaction_type",
            "method",
            "amount",
            "currency",
            "reference",
            "phone_number",
            "mobile_operator",
            "transaction_date",
            "facture",
            "depense",
            "caisse",
            "session_caisse",
            "note",
            "attachment",
        ]
        labels = {
            "transaction_type": "Type de paiement",
            "method": "Moyen de paiement",
            "amount": "Montant",
            "currency": "Devise",
            "reference": "Reference transaction",
            "phone_number": "Telephone Mobile Money",
            "mobile_operator": "Operateur Mobile Money",
            "transaction_date": "Date transaction",
            "facture": "Facture liee",
            "depense": "Depense liee",
            "caisse": "Caisse",
            "session_caisse": "Session caisse",
            "note": "Note",
            "attachment": "Piece justificative",
        }
        widgets = {
            "transaction_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "note": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, entreprise=None, user=None, **kwargs):
        self.entreprise = entreprise
        self.user = user
        super().__init__(*args, **kwargs)

        if entreprise is not None:
            self.fields["currency"].initial = getattr(entreprise, "devise", "") or "CDF"
            self.fields["facture"].queryset = Facture.objects.filter(
                entreprise=entreprise,
                statut__in=[Facture.Statut.EMISE, Facture.Statut.PAYEE],
            ).order_by("-date", "-id")
            self.fields["depense"].queryset = Depense.objects.filter(entreprise=entreprise).order_by("-date", "-id")
            self.fields["caisse"].queryset = Caisse.objects.filter(entreprise=entreprise, est_active=True).order_by("nom")
            self.fields["session_caisse"].queryset = (
                SessionCaisse.objects.filter(entreprise=entreprise, statut=SessionCaisse.Statut.OUVERTE)
                .select_related("caisse")
                .order_by("-date_ouverture", "-id")
            )

        self.fields["facture"].required = False
        self.fields["depense"].required = False
        self.fields["caisse"].required = False
        self.fields["session_caisse"].required = False
        self.fields["mobile_operator"].required = False
        self.fields["phone_number"].required = False
        self.fields["reference"].required = False
        self.fields["transaction_date"].initial = timezone.now()

        if user is not None and not user_has_permission(user, "payments.validate"):
            self.fields["confirm_now"].disabled = True
            self.fields["confirm_now"].help_text = "La confirmation est reservee aux roles habilites."

        for field in self.fields.values():
            css_class = "form-control"
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("method")
        mobile_operator = cleaned.get("mobile_operator")
        caisse = cleaned.get("caisse")
        session = cleaned.get("session_caisse")
        facture = cleaned.get("facture")
        depense = cleaned.get("depense")

        if session and caisse and session.caisse_id != caisse.id:
            self.add_error("session_caisse", "La session selectionnee n'appartient pas a cette caisse.")
        if session and not caisse:
            cleaned["caisse"] = session.caisse
        if method in PaymentTransaction.MOBILE_MONEY_METHODS and not mobile_operator:
            cleaned["mobile_operator"] = method
        if facture and depense:
            self.add_error("depense", "Choisissez une facture ou une depense, pas les deux.")
        return cleaned


class PaymentDecisionForm(forms.Form):
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "Note interne"}),
        label="Note",
    )

