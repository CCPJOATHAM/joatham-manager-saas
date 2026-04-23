from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import PasswordResetForm

from core.audit import record_audit_event

from core.services.world import get_default_currency_for_country
from core.services.world import get_country_choices, get_currency_choices


User = get_user_model()


class SignupForm(forms.Form):
    company_name = forms.CharField(max_length=100, label="Nom de l'entreprise")
    raison_sociale = forms.CharField(max_length=150, required=False, label="Raison sociale")
    owner_full_name = forms.CharField(max_length=150, label="Nom complet du propriétaire")
    email = forms.EmailField(label="E-mail")
    telephone = forms.CharField(max_length=50, required=False, label="Téléphone")
    pays = forms.ChoiceField(choices=(), label="Pays")
    devise = forms.ChoiceField(choices=(), label="Devise")
    password = forms.CharField(widget=forms.PasswordInput, label="Mot de passe")
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="Confirmation du mot de passe")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pays"].choices = get_country_choices()
        self.fields["devise"].choices = get_currency_choices()
        self.fields["pays"].initial = "RDC"
        self.fields["devise"].initial = get_default_currency_for_country("RDC")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cet e-mail. Veuillez vous connecter.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "La confirmation du mot de passe ne correspond pas.")
        if password:
            try:
                validate_password(password)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return cleaned_data


class SecurePasswordResetForm(PasswordResetForm):
    def save(self, *args, **kwargs):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        users = list(self.get_users(email))

        for user in users:
            entreprise = getattr(user, "entreprise", None)
            if entreprise is None:
                continue
            record_audit_event(
                entreprise=entreprise,
                utilisateur=user,
                action="password_reset_requested",
                module="auth",
                objet_type="User",
                objet_id=user.id,
                description=f"Demande de réinitialisation du mot de passe pour {user.username}.",
                metadata={"email": user.email},
            )

        return super().save(*args, **kwargs)
