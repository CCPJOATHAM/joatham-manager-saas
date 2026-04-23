import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class PasswordComplexityValidator:
    def validate(self, password, user=None):
        errors = []

        if not re.search(r"[A-Z]", password or ""):
            errors.append(_("Le mot de passe doit contenir au moins une lettre majuscule."))
        if not re.search(r"[a-z]", password or ""):
            errors.append(_("Le mot de passe doit contenir au moins une lettre minuscule."))
        if not re.search(r"\d", password or ""):
            errors.append(_("Le mot de passe doit contenir au moins un chiffre."))
        if not re.search(r"[^A-Za-z0-9]", password or ""):
            errors.append(_("Le mot de passe doit contenir au moins un caractere special."))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Votre mot de passe doit inclure au moins une majuscule, une minuscule, un chiffre et un caractere special."
        )
