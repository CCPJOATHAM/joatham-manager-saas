from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Caisse, MouvementCaisse


class CaisseForm(forms.ModelForm):
    class Meta:
        model = Caisse
        fields = ["nom", "code", "description", "devise", "est_active"]
        labels = {
            "nom": _("Nom de la caisse"),
            "code": _("Code"),
            "description": _("Description"),
            "devise": _("Devise"),
            "est_active": _("Caisse active"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nom"].widget.attrs.update({"placeholder": _("Ex. Caisse principale")})
        self.fields["code"].widget.attrs.update({"placeholder": "CAISSE-001"})
        self.fields["description"].widget = forms.Textarea(
            attrs={"rows": 3, "placeholder": _("Description ou emplacement de la caisse")}
        )
        self.fields["devise"].widget.attrs.update({"placeholder": "CDF"})


class OpenSessionForm(forms.Form):
    solde_initial = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        label=_("Solde initial"),
    )
    commentaire_ouverture = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": _("Commentaire d'ouverture")}),
        label=_("Commentaire"),
    )


class CloseSessionForm(forms.Form):
    solde_reel = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        label=_("Solde reel"),
    )
    commentaire_fermeture = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": _("Commentaire de fermeture")}),
        label=_("Commentaire"),
    )


class MouvementCaisseForm(forms.Form):
    MANUAL_MOVEMENT_CHOICES = [
        (MouvementCaisse.TypeMouvement.ENTREE, _("Entree")),
        (MouvementCaisse.TypeMouvement.SORTIE, _("Sortie")),
        (MouvementCaisse.TypeMouvement.DEPENSE, _("Depense")),
        (MouvementCaisse.TypeMouvement.AJUSTEMENT, _("Ajustement")),
    ]

    type_mouvement = forms.ChoiceField(choices=MANUAL_MOVEMENT_CHOICES, label=_("Type de mouvement"))
    montant = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        label=_("Montant"),
    )
    libelle = forms.CharField(max_length=255, label=_("Libelle"))
    reference = forms.CharField(required=False, max_length=100, label=_("Reference"))
    commentaire = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": _("Commentaire interne")}),
        label=_("Commentaire"),
    )


class SessionDecisionForm(forms.Form):
    commentaire = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": _("Commentaire de validation")}),
        label=_("Commentaire"),
    )
