from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _


User = get_user_model()


ROLE_CHOICES = [
    (User.Role.GESTIONNAIRE, _("Gestionnaire")),
    (User.Role.COMPTABLE, _("Comptable")),
]


class UserManagementForm(forms.Form):
    full_name = forms.CharField(max_length=150, label=_("Nom"))
    email = forms.EmailField(label=_("E-mail"))
    telephone = forms.CharField(max_length=50, required=False, label=_("Telephone"))
    role = forms.ChoiceField(choices=ROLE_CHOICES, label=_("Role"))
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label=_("Mot de passe"),
        help_text=_("Laissez ce champ vide lors d'une modification pour conserver le mot de passe actuel."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].widget.attrs.update(
            {
                "placeholder": _("Nom complet de l'utilisateur"),
                "autocomplete": "name",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "placeholder": "adresse@entreprise.com",
                "autocomplete": "email",
            }
        )
        self.fields["telephone"].widget.attrs.update(
            {
                "placeholder": "+243...",
                "autocomplete": "tel",
            }
        )
        self.fields["role"].widget.attrs.update({"aria-label": _("Role")})
        self.fields["password"].widget.attrs.update(
            {
                "placeholder": _("Mot de passe securise"),
                "autocomplete": "new-password",
            }
        )


class ProfileUpdateForm(forms.ModelForm):
    full_name = forms.CharField(
        max_length=150,
        required=False,
        label=_("Nom complet"),
    )

    class Meta:
        model = User
        fields = ["full_name", "telephone", "preferred_language", "profile_photo"]
        labels = {
            "telephone": _("Telephone"),
            "preferred_language": _("Langue preferee"),
            "profile_photo": _("Photo de profil"),
        }
        widgets = {
            "telephone": forms.TextInput(attrs={"placeholder": "+243...", "autocomplete": "tel"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        full_name = ""
        if self.instance and self.instance.pk:
            full_name = f"{self.instance.first_name} {self.instance.last_name}".strip()
        self.fields["full_name"].initial = full_name
        self.fields["full_name"].widget.attrs.update(
            {
                "placeholder": _("Votre nom complet"),
                "autocomplete": "name",
            }
        )
        self.fields["preferred_language"].widget.attrs.update({"aria-label": _("Langue preferee")})
        self.fields["profile_photo"].widget.attrs.update({"accept": "image/*"})

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = (self.cleaned_data.get("full_name") or "").strip()
        parts = full_name.split()
        if not parts:
            user.first_name = ""
            user.last_name = ""
        elif len(parts) == 1:
            user.first_name = parts[0]
            user.last_name = ""
        else:
            user.first_name = parts[0]
            user.last_name = " ".join(parts[1:])

        if commit:
            user.save()
        return user
