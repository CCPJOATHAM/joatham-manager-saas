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
