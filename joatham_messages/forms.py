import re

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .models import PublicQuestion, SuggestionSuperAdmin


User = get_user_model()

MAX_MESSAGE_LENGTH = 5000
MIN_MESSAGE_LENGTH = 10
PHONE_PATTERN = re.compile(r"^[0-9+().\-\s]{6,30}$")


def _clean_trimmed_required(value, *, field_label, min_length=1, max_length=None):
    value = (value or "").strip()
    if not value:
        raise forms.ValidationError(_("%(field)s est obligatoire.") % {"field": field_label})
    if min_length and len(value) < min_length:
        raise forms.ValidationError(
            _("%(field)s doit contenir au moins %(min)d caracteres.")
            % {"field": field_label, "min": min_length}
        )
    if max_length and len(value) > max_length:
        raise forms.ValidationError(
            _("%(field)s ne doit pas depasser %(max)d caracteres.")
            % {"field": field_label, "max": max_length}
        )
    return value


class ConversationCreateForm(forms.Form):
    sujet = forms.CharField(max_length=180, label=_("Sujet"))
    participants = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label=_("Participants"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    contenu = forms.CharField(
        label=_("Message"),
        max_length=MAX_MESSAGE_LENGTH,
        widget=forms.Textarea(attrs={"rows": 6}),
    )

    def __init__(self, *args, entreprise=None, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entreprise = entreprise
        self.current_user = current_user
        users = User.objects.none()
        if entreprise is not None:
            users = User.objects.filter(entreprise=entreprise, is_active=True).order_by(
                "first_name",
                "last_name",
                "username",
            )
            if current_user is not None:
                users = users.exclude(id=current_user.id)
        self.fields["participants"].queryset = users
        self.fields["sujet"].widget.attrs.update({"placeholder": _("Sujet de la conversation")})
        self.fields["contenu"].widget.attrs.update({"placeholder": _("Votre message"), "maxlength": MAX_MESSAGE_LENGTH})

    def clean_sujet(self):
        return _clean_trimmed_required(self.cleaned_data.get("sujet"), field_label=_("Sujet"), max_length=180)

    def clean_contenu(self):
        return _clean_trimmed_required(
            self.cleaned_data.get("contenu"),
            field_label=_("Message"),
            max_length=MAX_MESSAGE_LENGTH,
        )


class MessageReplyForm(forms.Form):
    contenu = forms.CharField(
        label=_("Message"),
        required=False,
        max_length=MAX_MESSAGE_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": _("Ecrire une reponse"), "maxlength": MAX_MESSAGE_LENGTH}),
    )

    def clean_contenu(self):
        return (self.cleaned_data.get("contenu") or "").strip()


class SuggestionSuperAdminForm(forms.ModelForm):
    class Meta:
        model = SuggestionSuperAdmin
        fields = ["sujet", "message"]
        labels = {
            "sujet": _("Sujet"),
            "message": _("Suggestion"),
        }
        widgets = {
            "sujet": forms.TextInput(attrs={"placeholder": _("Ex. amelioration du module facturation"), "maxlength": 180}),
            "message": forms.Textarea(attrs={"rows": 6, "placeholder": _("Decrivez votre besoin ou votre suggestion"), "maxlength": MAX_MESSAGE_LENGTH}),
        }

    def clean_sujet(self):
        return _clean_trimmed_required(self.cleaned_data.get("sujet"), field_label=_("Sujet"), max_length=180)

    def clean_message(self):
        return _clean_trimmed_required(
            self.cleaned_data.get("message"),
            field_label=_("Suggestion"),
            min_length=MIN_MESSAGE_LENGTH,
            max_length=MAX_MESSAGE_LENGTH,
        )


class PublicQuestionForm(forms.ModelForm):
    site_web = forms.CharField(required=False, widget=forms.HiddenInput, label="")

    class Meta:
        model = PublicQuestion
        fields = ["nom", "email", "telephone", "entreprise", "sujet", "message"]
        labels = {
            "nom": _("Nom"),
            "email": _("E-mail"),
            "telephone": _("Telephone"),
            "entreprise": _("Entreprise"),
            "sujet": _("Sujet"),
            "message": _("Message"),
        }
        widgets = {
            "nom": forms.TextInput(attrs={"placeholder": _("Votre nom"), "maxlength": 150}),
            "email": forms.EmailInput(attrs={"placeholder": "adresse@example.com"}),
            "telephone": forms.TextInput(attrs={"placeholder": "+243...", "maxlength": 50}),
            "entreprise": forms.TextInput(attrs={"placeholder": _("Nom de votre entreprise"), "maxlength": 150}),
            "sujet": forms.TextInput(attrs={"placeholder": _("Votre question"), "maxlength": 180}),
            "message": forms.Textarea(attrs={"rows": 6, "placeholder": _("Votre message"), "maxlength": MAX_MESSAGE_LENGTH}),
        }

    def clean_nom(self):
        return _clean_trimmed_required(self.cleaned_data.get("nom"), field_label=_("Nom"), max_length=150)

    def clean_email(self):
        return _clean_trimmed_required(self.cleaned_data.get("email"), field_label=_("E-mail"), max_length=254).lower()

    def clean_telephone(self):
        value = (self.cleaned_data.get("telephone") or "").strip()
        if value and not PHONE_PATTERN.match(value):
            raise forms.ValidationError(_("Telephone invalide. Utilisez uniquement chiffres, espaces et +().-"))
        return value

    def clean_entreprise(self):
        value = (self.cleaned_data.get("entreprise") or "").strip()
        if len(value) > 150:
            raise forms.ValidationError(_("Entreprise ne doit pas depasser 150 caracteres."))
        return value

    def clean_sujet(self):
        return _clean_trimmed_required(self.cleaned_data.get("sujet"), field_label=_("Sujet"), max_length=180)

    def clean_message(self):
        return _clean_trimmed_required(
            self.cleaned_data.get("message"),
            field_label=_("Message"),
            min_length=MIN_MESSAGE_LENGTH,
            max_length=MAX_MESSAGE_LENGTH,
        )

    def clean_site_web(self):
        if (self.cleaned_data.get("site_web") or "").strip():
            raise forms.ValidationError(_("Demande invalide."))
        return ""


class SuperAdminRequestFilterForm(forms.Form):
    TYPE_CHOICES = (
        ("", _("Tous les types")),
        ("suggestion", _("Suggestions")),
        ("question", _("Questions publiques")),
    )

    q = forms.CharField(required=False, max_length=120)
    type = forms.ChoiceField(required=False, choices=TYPE_CHOICES)
    statut = forms.ChoiceField(
        required=False,
        choices=[("", _("Tous les statuts"))] + list(SuggestionSuperAdmin.Statut.choices),
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean_q(self):
        return (self.cleaned_data.get("q") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError(_("La date de debut doit etre avant la date de fin."))
        return cleaned_data


class SuperAdminStatusUpdateForm(forms.Form):
    item_type = forms.ChoiceField(choices=(("suggestion", _("Suggestion")), ("question", _("Question publique"))))
    item_id = forms.IntegerField(min_value=1)
    status = forms.ChoiceField(choices=SuggestionSuperAdmin.Statut.choices)


class PublicQuestionReplyForm(forms.Form):
    reponse = forms.CharField(
        label=_("Reponse"),
        max_length=MAX_MESSAGE_LENGTH,
        widget=forms.Textarea(
            attrs={
                "rows": 9,
                "maxlength": MAX_MESSAGE_LENGTH,
                "placeholder": _("Redigez une reponse claire pour le visiteur"),
            }
        ),
    )

    def clean_reponse(self):
        return _clean_trimmed_required(
            self.cleaned_data.get("reponse"),
            field_label=_("Reponse"),
            min_length=MIN_MESSAGE_LENGTH,
            max_length=MAX_MESSAGE_LENGTH,
        )
