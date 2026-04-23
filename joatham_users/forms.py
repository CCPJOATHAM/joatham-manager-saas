from django import forms
from django.contrib.auth import get_user_model


User = get_user_model()


ROLE_CHOICES = [
    (User.Role.GESTIONNAIRE, "Gestionnaire"),
    (User.Role.COMPTABLE, "Comptable"),
]


class UserManagementForm(forms.Form):
    full_name = forms.CharField(max_length=150, label="Nom")
    email = forms.EmailField(label="E-mail")
    telephone = forms.CharField(max_length=50, required=False, label="Téléphone")
    role = forms.ChoiceField(choices=ROLE_CHOICES, label="Rôle")
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label="Mot de passe",
        help_text="Laissez ce champ vide lors d'une modification pour conserver le mot de passe actuel.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].widget.attrs.update(
            {
                "placeholder": "Nom complet de l'utilisateur",
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
        self.fields["role"].widget.attrs.update({"aria-label": "Rôle"})
        self.fields["password"].widget.attrs.update(
            {
                "placeholder": "Mot de passe sécurisé",
                "autocomplete": "new-password",
            }
        )
