from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from joatham_caisse.models import Caisse

from .models import AvanceSalaire, DemandeConge, DocumentRH, Employe, PaiementSalaire, Poste, Presence


User = get_user_model()


class PosteForm(forms.ModelForm):
    class Meta:
        model = Poste
        fields = ["nom", "description", "actif"]
        labels = {
            "nom": _("Nom du poste RH"),
            "description": _("Description"),
            "actif": _("Poste RH actif"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nom"].widget.attrs.update({"placeholder": _("Exemple : Responsable stock")})
        self.fields["description"].widget.attrs.update({"placeholder": _("Fonction reelle et responsabilites principales")})


class EmployeForm(forms.ModelForm):
    class Meta:
        model = Employe
        fields = [
            "matricule",
            "nom",
            "prenom",
            "sexe",
            "telephone",
            "email",
            "adresse",
            "user",
            "poste",
            "type_contrat",
            "date_embauche",
            "salaire_base",
            "statut",
            "actif",
        ]
        labels = {
            "matricule": _("Matricule"),
            "nom": _("Nom"),
            "prenom": _("Prenom"),
            "sexe": _("Sexe"),
            "telephone": _("Telephone"),
            "email": _("Email"),
            "adresse": _("Adresse"),
            "user": _("Compte utilisateur lie"),
            "poste": _("Poste RH"),
            "type_contrat": _("Type de contrat"),
            "date_embauche": _("Date d'embauche"),
            "salaire_base": _("Salaire de base"),
            "statut": _("Statut"),
            "actif": _("Employe actif"),
        }
        widgets = {
            "date_embauche": forms.DateInput(attrs={"type": "date"}),
            "adresse": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, entreprise=None, can_link_user=False, **kwargs):
        super().__init__(*args, **kwargs)
        if can_link_user:
            linked_user_ids = Employe.objects.filter(user__isnull=False)
            if self.instance and self.instance.pk:
                linked_user_ids = linked_user_ids.exclude(pk=self.instance.pk)
            linked_user_ids = linked_user_ids.values_list("user_id", flat=True)
            self.fields["user"].queryset = (
                User.objects.filter(entreprise=entreprise)
                .exclude(role=User.Role.SUPER_ADMIN)
                .exclude(id__in=linked_user_ids)
                .order_by("first_name", "last_name", "email", "username")
            )
            self.fields["user"].required = False
            self.fields["user"].help_text = _(
                "Optionnel. Le compte utilisateur permet a cet employe de se connecter a JOATHAM Manager. "
                "Le role d'acces reste gere dans le module Utilisateurs."
            )
            self.fields["user"].empty_label = _("Aucun compte utilisateur lie")
        else:
            self.fields.pop("user")
        self.fields["poste"].queryset = Poste.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "id")
        self.fields["poste"].required = False
        self.fields["salaire_base"].min_value = 0
        self.fields["matricule"].widget.attrs.update({"placeholder": _("Exemple : RH-001")})
        self.fields["nom"].widget.attrs.update({"placeholder": _("Nom de famille")})
        self.fields["prenom"].widget.attrs.update({"placeholder": _("Prenom")})
        self.fields["telephone"].widget.attrs.update({"placeholder": _("Telephone")})
        self.fields["email"].widget.attrs.update({"placeholder": _("email@exemple.com")})
        self.fields["salaire_base"].widget.attrs.update({"placeholder": "0.00", "min": "0", "step": "0.01"})


class PresenceForm(forms.ModelForm):
    class Meta:
        model = Presence
        fields = ["employe", "date", "statut", "heure_arrivee", "heure_depart", "note"]
        labels = {
            "employe": _("Employe"),
            "date": _("Date"),
            "statut": _("Statut"),
            "heure_arrivee": _("Heure d'arrivee"),
            "heure_depart": _("Heure de depart"),
            "note": _("Note"),
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "heure_arrivee": forms.TimeInput(attrs={"type": "time"}),
            "heure_depart": forms.TimeInput(attrs={"type": "time"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employe"].queryset = Employe.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "prenom", "id")
        self.fields["note"].widget.attrs.update({"placeholder": _("Observation courte")})


class DemandeCongeForm(forms.ModelForm):
    class Meta:
        model = DemandeConge
        fields = ["employe", "type_conge", "date_debut", "date_fin", "motif"]
        labels = {
            "employe": _("Employe"),
            "type_conge": _("Type de conge"),
            "date_debut": _("Date debut"),
            "date_fin": _("Date fin"),
            "motif": _("Motif"),
        }
        widgets = {
            "date_debut": forms.DateInput(attrs={"type": "date"}),
            "date_fin": forms.DateInput(attrs={"type": "date"}),
            "motif": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employe"].queryset = Employe.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "prenom", "id")
        self.fields["motif"].widget.attrs.update({"placeholder": _("Motif ou precision courte")})


class DocumentRHForm(forms.ModelForm):
    class Meta:
        model = DocumentRH
        fields = ["employe", "type_document", "titre", "description", "date_document"]
        labels = {
            "employe": _("Employe"),
            "type_document": _("Type de document"),
            "titre": _("Titre"),
            "description": _("Description"),
            "date_document": _("Date du document"),
        }
        widgets = {
            "date_document": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employe"].queryset = Employe.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "prenom", "id")
        self.fields["titre"].widget.attrs.update({"placeholder": _("Exemple : Contrat de travail")})
        self.fields["description"].widget.attrs.update({"placeholder": _("Reference ou note interne")})


class AvanceSalaireForm(forms.ModelForm):
    class Meta:
        model = AvanceSalaire
        fields = ["employe", "date_avance", "montant", "motif", "statut", "mode_paiement", "reference"]
        labels = {
            "employe": _("Employé"),
            "date_avance": _("Date de l'avance"),
            "montant": _("Montant"),
            "motif": _("Motif"),
            "statut": _("Statut"),
            "mode_paiement": _("Mode de paiement"),
            "caisse": _("Caisse"),
            "reference": _("Référence"),
        }
        widgets = {
            "date_avance": forms.DateInput(attrs={"type": "date"}),
            "motif": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employe"].queryset = Employe.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "prenom", "id")
        self.fields["montant"].widget.attrs.update({"min": "0.01", "step": "0.01", "placeholder": "0.00"})
        self.fields["motif"].widget.attrs.update({"placeholder": _("Motif de l'avance")})
        self.fields["reference"].widget.attrs.update({"placeholder": _("Référence de paiement")})


class PaiementSalaireForm(forms.ModelForm):
    class Meta:
        model = PaiementSalaire
        fields = [
            "employe",
            "periode_mois",
            "periode_annee",
            "salaire_base",
            "primes",
            "retenues",
            "montant_paye",
            "date_paiement",
            "mode_paiement",
            "caisse",
            "reference",
            "notes",
        ]
        labels = {
            "employe": _("Employé"),
            "periode_mois": _("Mois"),
            "periode_annee": _("Année"),
            "salaire_base": _("Salaire de base"),
            "primes": _("Primes"),
            "retenues": _("Retenues"),
            "montant_paye": _("Montant payé"),
            "date_paiement": _("Date de paiement"),
            "mode_paiement": _("Mode de paiement"),
            "reference": _("Référence"),
            "notes": _("Notes"),
        }
        widgets = {
            "date_paiement": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employe"].queryset = Employe.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "prenom", "id")
        self.fields["caisse"].queryset = Caisse.objects.filter(entreprise=entreprise, est_active=True).order_by("nom", "id")
        self.fields["caisse"].required = False
        self.fields["caisse"].empty_label = _("Sans caisse")
        self.fields["caisse"].help_text = _("Optionnel. Une session de caisse ouverte est requise pour créer la sortie de caisse.")
        for field_name in ["salaire_base", "primes", "retenues", "montant_paye"]:
            self.fields[field_name].widget.attrs.update({"min": "0", "step": "0.01", "placeholder": "0.00"})
        self.fields["periode_mois"].widget.attrs.update({"min": "1", "max": "12"})
        self.fields["periode_annee"].widget.attrs.update({"min": "2000"})
        self.fields["reference"].widget.attrs.update({"placeholder": _("Référence de paiement")})
        self.fields["notes"].widget.attrs.update({"placeholder": _("Note interne sur le paiement")})
