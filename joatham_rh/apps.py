from django.utils.translation import gettext_lazy
from django.apps import AppConfig


class JoathamRhConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joatham_rh"
    verbose_name = gettext_lazy("Ressources humaines")
